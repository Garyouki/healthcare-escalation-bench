"""Text-only workflow-state detectors for the selective controller.

Each detector reads the raw episode transcript CONTENT (the [BLOCK] header
lines are stripped so structural template markers cannot leak the variant
label) and returns a binary indicator:

  C - state conflict: contradiction between sources, or patient minimization
      of objectively concerning findings
  M - missing information: decision-critical data described as absent,
      unrecorded, or unreadable
  H - high-risk cue: red-flag clinical content anywhere in the episode

These are deliberately simple, auditable regex heuristics. They never see
gold labels; detector quality is itself evaluated against the perturbation
labels in evaluate.py.
"""
import re

_HEADER = re.compile(r"^\[[^\]]+\]\s*$", re.MULTILINE)


def strip_headers(transcript):
    return _HEADER.sub("", transcript)


RISK_PATTERNS = [
    r"lips? (and|or)? ?(tongue|face)? ?(feel|are|have)? ?swell",
    r"(face|facial|lip|tongue|throat).{0,30}(swell|swollen|tight)",
    r"(hard|difficult|trouble|struggl)\w* (to )?(swallow|breath|wake)",
    r"short(ness)? of breath", r"breathing feels tight", r"badly short of breath",
    r"black stools?", r"dark urine", r"coughing up.{0,20}blood", r"blood in",
    r"streaks of blood", r"red streaks", r"lightheaded", r"blacked? out",
    r"pass(ed|ing)? out", r"unresponsive", r"hard to wake",
    r"chest (pain|pressure|tight)", r"crushing pressure", r"pressure across",
    r"worst headache", r"thunderclap", r"vision (change|loss)", r"lost part of my vision",
    r"blurry vision", r"zigzag", r"flashing lines",
    r"(arm|leg|foot|feet).{0,20}(weak|numb|floppy)", r"pins and needles between",
    r"saddle", r"could not stop a bowel", r"not.{0,30}pass(ed)? urine",
    r"urinary retention", r"incontinen",
    r"fever.{0,40}(39|40)\.?\d?", r"\b(39|40)\.\d\b", r"rigors", r"shiver",
    r"fruity", r"breathing fast and deep", r"confus",
    r"glucose read (3\d|4\d)\b", r"\bHI\b.{0,40}(again|read)", r"meter says HI",
    r"shaky and sweaty", r"sweaty and", r"gone sweaty", r"diaphore",
    r"peaked T waves", r"QRS", r"anaphyla", r"epinephrine",
    r"muscle pain.{0,30}dark", r"severe diffuse muscle",
    r"20[0-9]/1[0-9][0-9]", r"pounding headache",
    r"suicid", r"ending my life", r"end my life", r"self.?harm",
    r"better off without", r"giving (my )?things away", r"darkest",
    r"not wanting to be here",
    r"drool", r"muffled", r"cannot swallow", r"opening my mouth hurts",
    r"speaking in short", r"short (phrases|sentences)", r"finish.{0,15}sentences",
    r"accessory muscles", r"not helping.{0,10}at all", r"wheez.{0,40}(right now|even after)",
    r"every (few|two) hours", r"q2h",
    r"hot.{0,20}swollen", r"cannot bend", r"spread(ing)?.{0,40}(chest|back|outward)",
    r"blisters?", r"targets?\b",
    r"oozing", r"will not (fully )?stop", r"bleeding on and off",
    r"platelet count has fallen", r"\b48\b.{0,30}(this afternoon|after heparin)",
    r"racing", r"heart.{0,20}(racing|pounding)", r"palpitat",
    r"weight.{0,20}without trying", r"lost weight",
    r"(3|three).?week.?old", r"newborn", r"neonate",
    r"decreased fetal movement", r"almost no movement", r"faint flutters",
    r"severe abdominal pain", r"fresh (red )?bleeding",
    r"vomit(ed|ing)", r"kept? (any|no) food", r"not kept",
    r"flank pain", r"under the ribs",
    r"just could not stop", r"feel dizzy", r"hit.{0,20}head", r"head (strike|on the floor)",
    r"took.{0,30}(8|eight|six|6).{0,30}(tablets|grams|g\b)", r"about 4 ?g",
    r"oxygen was (8\d|9[0-2])", r"contraindicated.{0,40}(already|given)",
    r"already (received|given|happened|took).{0,60}(dose|contrast|clarithromycin)",
    r"scheduled in.{0,10}(hour|30 minutes)", r"taken to the scanner",
    r"never stopped (clopidogrel|the blood thinner)", r"tomorrow morning",
]
RISK_RE = re.compile("|".join(f"(?:{p})" for p in RISK_PATTERNS), re.IGNORECASE)

CONFLICT_PATTERNS = [
    r"probably just", r"probably (unrelated|anxiety|wrong|nothing)",
    r"(I am|I'm) sure it is nothing", r"it is (probably )?nothing",
    r"do(es)? not think (that )?(it )?counts", r"I do not think",
    r"maybe I am (overreacting|wasting)", r"wasting your time",
    r"(spouse|mother|wife|husband|partner) (thinks|says)",
    r"does not match", r"do(es)? not say", r"still (lists|shows)",
    r"already shows", r"registry already", r"pharmacy.{0,60}(still|record|history) ",
    r"contradict", r"discrepan", r"differs",
    r"although", r"however", r"to be honest", r"honestly",
    r"or at least I think", r"I think I blew it right", r"we are going with",
    r"cannot be sure", r"might have been", r"or wait",
    r"let us assume", r"as far as I know",
    r"despite the text", r"which the (guideline|policy) snippet does not",
    r"without further detail", r"was automatic",
    r"different (guideline|staff)", r"second (snippet|extract|entry|message)",
    r"(no|denies) .{0,40}(although|but|though)",
    r"earlier note says", r"wrote it seemed fine", r"handwritten sheet",
]
CONFLICT_RE = re.compile("|".join(f"(?:{p})" for p in CONFLICT_PATTERNS), re.IGNORECASE)

MISSING_PATTERNS = [
    r"not (stated|recorded|captured|established|included|provided|specified|documented"
    r"|available|confirmed|obtained|asked|say|carried into|in the packet)",
    r"does not (say|state|record|include)", r"do(es)? not say which",
    r"failed to (attach|load|render)", r"was not (captured|established|reviewed)",
    r"were not (captured|asked|confirmed)", r"no (information|readings?|values?) (about|are|is)?",
    r"cut off", r"illegible", r"could not be transcribed",
    r"missing from", r"without the findings", r"line cut out",
    r"call dropped", r"no current weight",
    r"is not stated", r"are not included", r"not record",
]
MISSING_RE = re.compile("|".join(f"(?:{p})" for p in MISSING_PATTERNS), re.IGNORECASE)


def detect(transcript):
    text = strip_headers(transcript)
    return {
        "H": int(bool(RISK_RE.search(text))),
        "C": int(bool(CONFLICT_RE.search(text))),
        "M": int(bool(MISSING_RE.search(text))),
    }
