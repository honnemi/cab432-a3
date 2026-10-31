import hashlib
import json
import os
import shutil
import signal
import ssl
from datetime import datetime, timezone

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from pdf_generator import generate_phrasebook, upload_pdf
from json_repair import repair_json

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)

# AWS Systems Manager Parameter Store
BOOTSTRAP_REGION = os.environ.get("AWS_REGION", "ap-southeast-2")
PARAMETER_PATH = "/n11496096/phrasebook/"

ssm = boto3.client("ssm", region_name=BOOTSTRAP_REGION)


def load_config():
    parameters = {}
    next_token = None

    while True:
        request = {
            "Path": PARAMETER_PATH,
            "Recursive": True,
            "WithDecryption": True,
        }

        if next_token:
            request["NextToken"] = next_token

        response = ssm.get_parameters_by_path(**request)

        for parameter in response.get("Parameters", []):
            name = parameter["Name"].removeprefix(PARAMETER_PATH)
            parameters[name] = parameter["Value"]

        next_token = response.get("NextToken")

        if not next_token:
            break

    required = [
        "model-id",
        "table-name",
        "sqs-queue-url",
        "max-receives",
        "batch-size",
        "cache-ttl-seconds",
        "metric-namespace",
    ]

    missing = [name for name in required if name not in parameters]

    if missing:
        raise RuntimeError(
            "Missing required SSM parameters: "
            + ", ".join(f"{PARAMETER_PATH}{name}" for name in missing)
        )

    return parameters


CONFIG = load_config()

REGION = CONFIG.get("region", BOOTSTRAP_REGION)
MODEL_ID = CONFIG["model-id"]
TABLE_NAME = CONFIG["table-name"]
QUEUE_URL = CONFIG["sqs-queue-url"]
MAX_RECEIVES = int(CONFIG["max-receives"])
BATCH_SIZE = int(CONFIG["batch-size"])
CACHE_TTL_SECONDS = int(CONFIG["cache-ttl-seconds"])
METRIC_NAMESPACE = CONFIG["metric-namespace"]

MEMCACHE_HOST = CONFIG.get("memcache-host") or None
MEMCACHE_PORT = int(CONFIG.get("memcache-port", "11211"))
MEMCACHE_TLS = CONFIG.get("memcache-tls", "false").lower() == "true"


# AWS service clients
retry_config = Config(
    retries={
        "max_attempts": 5,
        "mode": "adaptive",
    }
)

bedrock = boto3.client(
    "bedrock-runtime",
    region_name=REGION,
    config=retry_config,
)

sqs = boto3.client("sqs", region_name=REGION)
cloudwatch = boto3.client("cloudwatch", region_name=REGION)
dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)

print(f"Configuration loaded from {PARAMETER_PATH}")
print(f"Region: {REGION}")
print(f"Model: {MODEL_ID}")
print(f"Job table: {TABLE_NAME}")
print(
    f"Memcached: {MEMCACHE_HOST}:{MEMCACHE_PORT}"
    if MEMCACHE_HOST
    else "Memcached: disabled"
)


# Graceful shutdown
shutting_down = False


def _handle_shutdown(signum, frame):
    global shutting_down
    shutting_down = True
    print("Shutdown requested; finishing current job")


signal.signal(signal.SIGTERM, _handle_shutdown)
signal.signal(signal.SIGINT, _handle_shutdown)


# Memcached
cache = None

if MEMCACHE_HOST:
    try:
        from pymemcache.client.base import Client as MemcacheClient

        cache = MemcacheClient(
            (MEMCACHE_HOST, MEMCACHE_PORT),
            connect_timeout=2,
            timeout=2,
            tls_context=(
                ssl.create_default_context() if MEMCACHE_TLS else None
            ),
        )

        cache.version()  # connectivity check (memcached has no PING)
        print(f"Connected to Memcached at {MEMCACHE_HOST}:{MEMCACHE_PORT}")

    except Exception as e:
        print(f"Memcached unavailable; continuing without cache: {e}")
        cache = None


def cache_key(phrase, language):
    """Key includes the phrase and target language, not formality.

    Memcached keys must be <= 250 bytes with no whitespace or control
    characters, so the phrase is hashed and the language is sanitised.
    """
    digest = hashlib.sha256(
        phrase.strip().lower().encode("utf-8")
    ).hexdigest()[:32]

    safe_language = "".join(
        ch if ch.isalnum() else "_"
        for ch in language.strip().lower()
    )

    return f"tr:v2:{safe_language}:{digest}"


def cache_get_many(phrases, language):
    if not cache:
        return {}

    try:
        unique_phrases = list(dict.fromkeys(phrases))

        key_to_phrase = {
            cache_key(phrase, language): phrase
            for phrase in unique_phrases
        }

        # get_many returns only the keys that were found
        found = cache.get_many(list(key_to_phrase.keys()))
        results = {}

        for key, value in found.items():
            try:
                results[key_to_phrase[key]] = json.loads(value)

            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                print(f"Invalid cached entry for {key}: {e}")

        return results

    except Exception as e:
        print(f"Memcached read failed; treating as cache miss: {e}")
        return {}


def cache_set_many(entries, language):
    if not cache or not entries:
        return

    try:
        mapping = {
            cache_key(phrase, language): json.dumps(
                entry, ensure_ascii=False
            ).encode("utf-8")
            for phrase, entry in entries.items()
        }

        failed = cache.set_many(
            mapping,
            expire=CACHE_TTL_SECONDS,
            noreply=False,
        )

        if failed:
            print(f"Memcached failed to store {len(failed)} key(s)")

    except Exception as e:
        print(f"Memcached write failed: {e}")


# CloudWatch cache metrics
def emit_cache_metrics(hits, misses):
    try:
        cloudwatch.put_metric_data(
            Namespace=METRIC_NAMESPACE,
            MetricData=[
                {
                    "MetricName": "CacheHits",
                    "Value": hits,
                    "Unit": "Count",
                },
                {
                    "MetricName": "CacheMisses",
                    "Value": misses,
                    "Unit": "Count",
                },
            ],
        )

    except Exception as e:
        print(f"Could not publish cache metrics: {e}")


# General helpers
def now():
    return datetime.now(timezone.utc).isoformat()


def update_job(job_id, status, extra=None, expected_status=None):
    """
    Updates the job status atomically using conditional expressions 
    to guarantee idempotency against duplicate SQS deliveries.
    """
    values = {
        ":status": status,
        ":updated": now(),
    }

    expression = "SET jobStatus = :status, updatedAt = :updated"
    condition = "attribute_exists(jobId)"

    if expected_status:
        values[":expected"] = expected_status
        condition += " AND jobStatus = :expected"

    if extra:
        for key, value in extra.items():
            values[f":{key}"] = value
            expression += f", {key} = :{key}"

    if status == "PROCESSING":
        expression += " REMOVE errorMessage"

    try:
        table.update_item(
            Key={"jobId": job_id},
            UpdateExpression=expression,
            ExpressionAttributeValues=values,
            ConditionExpression=condition,
        )
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def extract_json(text):
    start = text.find("{")

    if start == -1:
        raise ValueError("Model response contains no JSON object")

    raw = text[start:].strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(
            f"Model returned invalid JSON: {exc}. "
            "Attempting JSON repair."
        )
        result = json.loads(repair_json(raw))

    if not isinstance(result, dict):
        raise ValueError("Expected a JSON object")

    return result


# Batched translation
def translate_batch(phrases, target_language):
    list_as_string = "\n".join(
        f"{index}. {phrase}"
        for index, phrase in enumerate(phrases, start=1)
    )

    prompt = f"""
You are an expert language tutor helping English-speaking travellers.

Translate the following English phrases into {target_language}.

For EACH phrase:
1. Provide a natural, accurate translation.
2. Identify the tone of the original phrase where possible.
3. Classify the translation's formality as casual, polite, formal,
    or neutral/context-dependent.
4. Explain when the main translation is appropriate.
5. Suggest casual, polite, and formal alternatives where meaningful.
6. Use null for alternatives that are unnatural or unnecessary.
7. Provide standard romanisation where applicable.
8. Give a beginner-friendly pronunciation guide.
9. Explain the context of each alternative.

Formality scale:
1 = casual or informal
2 = polite or everyday respectful
3 = formal or highly respectful

Return exactly one valid JSON object.
Do not include Markdown, code fences, or surrounding explanations.
Use double quotes for JSON keys and string values.
Escape quotation marks and backslashes correctly.
Do not include trailing commas.
Return every input phrase exactly once, in the original order.
Use null for unavailable romanisation or alternatives.
Do not invent cultural rules or universal claims.

Use this exact structure:
{{
  "target_language": "{target_language}",
  "phrases": [
    {{
      "english": "Original English phrase",
      "translation": "Main translation",
      "romanisation": "Romanisation or null",
      "pronunciation_guide": "Pronunciation guide",
      "context": "When to use the main translation",
      "formality": {{
        "level": "polite",
        "score": 2,
        "explanation": "Brief explanation of the tone"
      }},
      "alternatives": {{
        "casual": {{
          "translation": "Casual alternative",
          "romanisation": "Romanisation or null",
          "pronunciation_guide": "Pronunciation guide",
          "context": "When this version is appropriate"
        }},
        "polite": null,
        "formal": {{
          "translation": "Formal alternative",
          "romanisation": "Romanisation or null",
          "pronunciation_guide": "Pronunciation guide",
          "context": "When this version is appropriate"
        }}
      }}
    }}
  ]
}}

Input phrases:
{list_as_string}
"""

    last_error = None

    for attempt in range(2):
        try:
            response = bedrock.converse(
                modelId=MODEL_ID,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "text": (
                                    prompt
                                    if attempt == 0
                                    else prompt + """
IMPORTANT: Your previous response was invalid JSON.
Regenerate the entire response from scratch.
Check that all objects and arrays are closed,
all commas are correct, and all strings are escaped.
Return only valid JSON.
"""
                                )
                            }
                        ],
                    }
                ],
                inferenceConfig={
                    "maxTokens": 8192,
                    "temperature": 0.0,
                },
            )

            # Log Bedrock token usage
            usage = response.get("usage", {})

            input_tokens = usage.get("inputTokens", 0)
            output_tokens = usage.get("outputTokens", 0)
            total_tokens = usage.get("totalTokens", input_tokens + output_tokens)

            logger.info(
                "Bedrock token usage | Input: %s | Output: %s | Total: %s",
                input_tokens,
                output_tokens,
                total_tokens
            )

            if response.get("stopReason") == "max_tokens":
                raise ValueError(
                    "The model response was truncated because "
                    "it reached the output-token limit. "
                    "Reduce the batch size."
                )

            content = response["output"]["message"]["content"]

            response_text = "".join(
                block["text"]
                for block in content
                if "text" in block
            )

            data = extract_json(response_text)

            if not isinstance(data, dict):
                raise ValueError(
                    "The model response must be a JSON object"
                )

            entries = data.get("phrases", [])

            if not isinstance(entries, list):
                raise ValueError(
                    "The model response field 'phrases' "
                    "must be a list"
                )

            if len(entries) != len(phrases):
                raise ValueError(
                    f"Model returned {len(entries)} phrases, "
                    f"expected {len(phrases)}"
                )

            for original, entry in zip(phrases, entries):
                if not isinstance(entry, dict):
                    raise ValueError(
                        "A translated phrase was not a JSON object"
                    )

                entry["english"] = original

                if "alternatives" not in entry:
                    entry["alternatives"] = {
                        "casual": None,
                        "polite": None,
                        "formal": None,
                    }

                if "formality" not in entry:
                    entry["formality"] = {
                        "level": "neutral",
                        "score": 2,
                        "explanation": (
                            "The model did not classify the tone."
                        ),
                    }

            return entries

        except json.JSONDecodeError as e:
            last_error = e
            print(
                f"Invalid model JSON on attempt {attempt + 1}/2: "
                f"{e}"
            )

        except ClientError as e:
            raise RuntimeError(
                f"Unable to invoke model '{MODEL_ID}': {e}"
            ) from e

        except ValueError as e:
            last_error = e
            print(
                f"Invalid model output on attempt {attempt + 1}/2: "
                f"{e}"
            )

    raise ValueError(
        f"Translation batch failed after 2 attempts: {last_error}"
    ) from last_error


def translate_phrases(phrases, target_language):
    """
    Retrieve cached translations, batch cache misses through Bedrock,
    and cache the complete translation and formality alternatives.
    """
    unique_phrases = list(dict.fromkeys(phrases))
    cached = cache_get_many(unique_phrases, target_language)

    misses = [
        phrase
        for phrase in unique_phrases
        if phrase not in cached
    ]

    results = dict(cached)

    for i in range(0, len(misses), BATCH_SIZE):
        batch = misses[i:i + BATCH_SIZE]

        translated_entries = translate_batch(
            batch,
            target_language,
        )

        batch_results = dict(zip(batch, translated_entries))
        results.update(batch_results)
        cache_set_many(batch_results, target_language)

    hits = len(unique_phrases) - len(misses)

    print(f"Cache: {hits} hit(s), {len(misses)} miss(es)")
    emit_cache_metrics(hits, len(misses))

    return {
        "target_language": target_language,
        "phrases": [
            {**results[phrase], "english": phrase}
            for phrase in phrases
        ],
    }


# SQS job processing
def process_message(message):
    body = json.loads(message["Body"])
    job_id = body["jobId"]

    item = table.get_item(
        Key={"jobId": job_id},
        ConsistentRead=True,
    ).get("Item")

    if not item:
        raise ValueError(f"Job {job_id} was not found in DynamoDB")

    current_status = item.get("jobStatus")

    if current_status == "COMPLETED":
        return job_id

    # Atomically attempt to claim the job (transitions PENDING/RETRYING -> PROCESSING)
    claimed = update_job(job_id, "PROCESSING", expected_status=current_status)
    if not claimed:
        print(f"Job {job_id} is already being processed by another worker. Skipping.")
        return job_id

    phrases = list(item["phrases"])
    target_language = item["targetLanguage"]
    phrasebook_name = item.get("phrasebookName", "My Phrasebook")

    result = translate_phrases(
        phrases,
        target_language,
    )

    output_path = os.path.join(
        "outputs",
        job_id,
        "booklet.pdf",
    )

    try:
        generate_phrasebook(
            result,
            job_id,
            output_path=output_path,
            phrasebook_name=phrasebook_name,
        )

        s3_result = upload_pdf(output_path, job_id)

    finally:
        shutil.rmtree(
            os.path.join("outputs", job_id),
            ignore_errors=True,
        )

    update_job(
        job_id,
        "COMPLETED",
        {
            "s3Bucket": s3_result["bucket"],
            "s3Key": s3_result["key"],
            "completedAt": now(),
        },
    )

    print(f"Completed phrasebook '{phrasebook_name}' for job {job_id}")

    return job_id


# SQS polling loop
def run_worker():
    print("SQS worker started")

    while not shutting_down:
        try:
            response = sqs.receive_message(
                QueueUrl=QUEUE_URL,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20,
                VisibilityTimeout=300,
                AttributeNames=["ApproximateReceiveCount"],
            )

        except ClientError as e:
            print(f"Unable to receive SQS messages: {e}")
            break

        for message in response.get("Messages", []):
            job_id = None

            try:
                job_id = json.loads(message["Body"]).get("jobId")

                process_message(message)

                sqs.delete_message(
                    QueueUrl=QUEUE_URL,
                    ReceiptHandle=message["ReceiptHandle"],
                )

                print(f"Completed job {job_id}")

            except Exception as e:
                print(f"Job {job_id} failed: {e}")

                receive_count = int(
                    message.get("Attributes", {}).get(
                        "ApproximateReceiveCount",
                        "1",
                    )
                )

                if job_id:
                    try:
                        status = (
                            "FAILED"
                            if receive_count >= MAX_RECEIVES
                            else "RETRYING"
                        )

                        update_job(
                            job_id,
                            status,
                            {"errorMessage": str(e)[:500]},
                        )

                    except Exception as update_error:
                        print(
                            f"Could not update job {job_id}: "
                            f"{update_error}"
                        )

            if shutting_down:
                break

    print("Worker exited cleanly")


if __name__ == "__main__":
    run_worker()