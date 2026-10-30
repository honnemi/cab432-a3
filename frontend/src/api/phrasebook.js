
const API_URL = import.meta.env.VITE_API_URL;

async function parseResponse(response) {
  const data = await response.json();

  if (!response.ok) {
    throw new Error(
      data.error || data.message || "Phrasebook request failed"
    );
  }

  return data;
}

export async function createPhrasebook(phrases, targetLanguage, phrasebookName) {
  const response = await fetch(API_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      phrases,
      targetLanguage,
      phrasebookName,
    }),
  });

  return parseResponse(response);
}

export async function getPhrasebookStatus(jobId) {
  const response = await fetch(
    `${API_URL}/${encodeURIComponent(jobId)}`
  );

  return parseResponse(response);
}
