export default function LanguageButton({ language, countryCode, selected }) {
  return (
    <div 
      className={`w-30 h-30 flex flex-col items-center justify-center gap-3 p-10 rounded-lg shadow-md cursor-pointer transition duration-300 ease-in-out hover:scale-105 ${
        selected ? 'bg-[#287D78] text-white' : 'bg-white text-[#171A21]'
      }`}
    >
      <span className={`fi fi-${countryCode} text-6xl rounded-md shadow-md`} />
      <span className="text-sm font-semibold">{language}</span>
    </div>
  );
}
