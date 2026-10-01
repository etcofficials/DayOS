"""Course starters. Starters are conveniences, never authorities.

The CBSE Class 10 starter creates the subjects the student chooses, the exam
dates they enter, and (optionally) chapter lists taken from the NCERT textbook
tables of contents. Those lists are marked *provisional*: syllabi change between
sessions (the 2023-24 rationalisation removed chapters, for example), so the
student is asked to compare them with the official CBSE curriculum for their
session, or to import that document instead. No exam paper pattern is built in;
blueprints come from official sample papers the student imports or from their
own settings.
"""

from __future__ import annotations

from datetime import date

STARTER_SOURCE = ("Starter list based on the NCERT Class 10 textbook contents (rationalised editions). "
                  "Check it against the official CBSE curriculum for your session.")

CBSE10_SUBJECTS: dict[str, dict[str, list[str]]] = {
    "Mathematics": {
        "": ["Real Numbers", "Polynomials", "Pair of Linear Equations in Two Variables", "Quadratic Equations",
             "Arithmetic Progressions", "Triangles", "Coordinate Geometry", "Introduction to Trigonometry",
             "Some Applications of Trigonometry", "Circles", "Areas Related to Circles", "Surface Areas and Volumes",
             "Statistics", "Probability"],
    },
    "Science": {
        "": ["Chemical Reactions and Equations", "Acids, Bases and Salts", "Metals and Non-metals",
             "Carbon and its Compounds", "Life Processes", "Control and Coordination",
             "How do Organisms Reproduce?", "Heredity", "Light – Reflection and Refraction",
             "The Human Eye and the Colourful World", "Electricity", "Magnetic Effects of Electric Current",
             "Our Environment"],
    },
    "Social Science": {
        "History": ["The Rise of Nationalism in Europe", "Nationalism in India", "The Making of a Global World",
                    "The Age of Industrialisation", "Print Culture and the Modern World"],
        "Geography": ["Resources and Development", "Forest and Wildlife Resources", "Water Resources", "Agriculture",
                      "Minerals and Energy Resources", "Manufacturing Industries", "Lifelines of National Economy"],
        "Political Science": ["Power Sharing", "Federalism", "Gender, Religion and Caste", "Political Parties",
                              "Outcomes of Democracy"],
        "Economics": ["Development", "Sectors of the Indian Economy", "Money and Credit",
                      "Globalisation and the Indian Economy"],
    },
    "English": {},
    "Hindi": {},
    "Information Technology": {},
}

MATHS_VARIANTS = ["Mathematics Standard", "Mathematics Basic"]


def create_cbse10(sf, session: str, subjects: list[str], exam_dates: dict[str, date | None],
                  include_chapters: bool, maths_variant: str = "Mathematics Standard", subject_repo=None) -> int:
    """Create a CBSE Class 10 course. Returns the course id."""
    course_id = sf.courses.create(f"CBSE Class 10 ({session})" if session else "CBSE Class 10", "school", session,
                                  "CBSE", "Class 10",
                                  "Created from the DayOS starter. Chapter lists (if added) are provisional — "
                                  "compare them with the official CBSE curriculum for your session.")
    for name in subjects:
        display = maths_variant if name == "Mathematics" else name
        subject_id = subject_repo.get_or_create(display) if subject_repo is not None else None
        sid = sf.courses.add_node(course_id, "subject", display, subject_id=subject_id,
                                  exam_date=exam_dates.get(name))
        if not include_chapters:
            continue
        groups = CBSE10_SUBJECTS.get(name, {})
        for group, chapters in groups.items():
            parent = sid
            if group:
                parent = sf.courses.add_node(course_id, "unit", group, parent_id=sid, source_ref=STARTER_SOURCE,
                                             confidence=0.7)
            for chapter in chapters:
                sf.courses.add_node(course_id, "chapter", chapter, parent_id=parent, source_ref=STARTER_SOURCE,
                                    confidence=0.7)
    return course_id


GENERIC_PRESETS = {
    "quick": {"label": "Quick quiz", "minutes": 10, "count": 8, "types": ["mcq", "tf", "fill"]},
    "medium": {"label": "Medium test", "minutes": 30, "count": 15, "types": ["mcq", "vsa", "sa"]},
    "full": {"label": "Long practice", "minutes": 90, "count": 30, "types": ["mcq", "assertion", "vsa", "sa", "la", "case"]},
}
