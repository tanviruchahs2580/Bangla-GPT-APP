"""Section labels for structured AI answers (SYSTEM_PROMPT rule ৬ / step 1.4).

Kept in a dependency-free module so both the tutor service and the mock
provider can share one source of truth without an import cycle.
"""

SECTION_SIMPLE = "সহজ ব্যাখ্যা:"
SECTION_EXAMPLE = "উদাহরণ:"
SECTION_POINTS = "মূল বিষয়:"
SECTION_CHECK = "তুমি বুঝেছ?"


# S1.13: low-data mode asks the model for a 1-2 sentence answer.
SHORT_ANSWER_INSTRUCTION = "উত্তর সংক্ষেপে দাও: শুধু 'সহজ ব্যাখ্যা:' অংশের ১-২টি বাক্য লেখো।"
