// GENERATED FILE — do not edit by hand.
// Source: data/vocabulary.json · regenerate with: python scripts/gen_vocabulary.py --write
// This module is the browser half of the shared in-game vocabulary. It classifies
// text a provider actually wrote; it never creates a diagnosis, a severity or a cause.
export const VOCABULARY_VERSION = 1;
export const IN_GAME_RULES = Object.freeze([
  Object.freeze({ status: "out", observation: "", label: "OUT / will not return wording", weight: 5, patterns: Object.freeze([/\bwill not return\b/i, /\bdid not return\b/i, /\bdoes not return\b/i, /\bwon't return\b/i, /\bru(?:led|ling) out\b/i, /\bout for the (?:game|remainder|rest of the game|day)\b/i, /\bmissed the remainder of the game\b/i, /\bmissed the rest of the game\b/i, /\bout for the season\b/i]) }),
  Object.freeze({ status: "questionable", observation: "", label: "RETURN UNCERTAIN wording", weight: 4, patterns: Object.freeze([/\bquestionable to return\b/i, /\breturn is questionable\b/i, /\bdoubtful to return\b/i, /\buncertain to return\b/i, /\breturn (?:is|remains) uncertain\b/i]) }),
  Object.freeze({ status: "evaluated", observation: "Concussion evaluation", label: "CONCUSSION PROTOCOL wording", weight: 3, patterns: Object.freeze([/\bconcussion protocol\b/i, /\bevaluated for a concussion\b/i, /\bbeing evaluated for a concussion\b/i, /\bentered the concussion protocol\b/i]) }),
  Object.freeze({ status: "evaluated", observation: "Medical tent evaluation", label: "MEDICAL TENT wording", weight: 3, patterns: Object.freeze([/\bblue (?:medical )?tent\b/i, /\bmedical tent\b/i, /\binjury tent\b/i]) }),
  Object.freeze({ status: "observed", observation: "Cart or stretcher", label: "CART / STRETCHER wording", weight: 2, patterns: Object.freeze([/\bcart(?:ed)? off\b/i, /\bcarted to the locker room\b/i, /\bon a stretcher\b/i, /\bstretcher\b/i, /\bimmobilized\b/i, /\bair cast\b/i]) }),
  Object.freeze({ status: "returned", observation: "Returned to the game", label: "RETURNED wording", weight: 2, patterns: Object.freeze([/\breturned to the game\b/i, /\breturned to the field\b/i, /\bback on the field\b/i, /\bhas returned\b/i, /\breturned after (?:halftime|the break)\b/i, /\bcleared to return\b/i]) }),
  Object.freeze({ status: "observed", observation: "Left game", label: "LEFT THE GAME wording", weight: 1, patterns: Object.freeze([/\bleft the game\b/i, /\bexited the game\b/i, /\bwent to the locker room\b/i, /\bwas taken to the locker room\b/i, /\bwalked off (?:the field )?(?:slowly|under his own power)\b/i]) }),
  Object.freeze({ status: "observed", observation: "Injury mentioned", label: "INJURY MENTIONED wording", weight: 1, patterns: Object.freeze([/\binjur(?:y|ed|ies)\b/i, /\bwent down\b/i, /\bdown on the (?:field|turf)\b/i, /\blimped\b/i, /\bwas hurt\b/i]) }),
]);

export const CONTEXTS = Object.freeze({
  inGame: Object.freeze(["did not return", "will not return", "ruled out", "left the game", "exited the game", "carted", "stretcher", "medical tent", "blue tent", "concussion protocol", "returned to the game", "returned to the field", "questionable to return", "missed the remainder of the game", "suffered", "went down", "in the first quarter", "in the second quarter", "in the third quarter", "in the fourth quarter", "before halftime", "after halftime", "at halftime"]),
  practiceExclusion: Object.freeze(["practice", "injury report", "did not participate", "did not practice", "limited participant", "full participant", "participation", "game status", "listed as", "estimated", "practice squad", "questionable for Sunday", "doubtful for Sunday", "out for Sunday", "will not play Sunday", "inactive", "has been ruled out for"]),
  gameDateHint: Object.freeze(["sunday", "monday", "thursday", "saturday", "week ", "tonight", "season opener"]),
});
