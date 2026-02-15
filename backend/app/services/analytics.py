"""
Analytics computation helpers.
Migrated from server.py (line ~9673).
"""


def extract_topic_from_rubric(rubric: str, subject_name: str = "General") -> str:
    """
    Extract topic from question rubric using keyword matching.
    Returns specific topic name based on keywords found in rubric.
    """
    if not rubric:
        return subject_name
    
    rubric_lower = rubric.lower()
    
    # Mathematics topics
    math_topics = {
        "Algebra": ["algebra", "algebraic", "equation", "equations", "variable", "variables", "expression", "expressions", 
                    "polynomial", "polynomials", "quadratic", "linear", "factorize", "factorization", "simplify", "solve for"],
        "Geometry": ["geometry", "geometric", "triangle", "triangles", "circle", "circles", "square", "rectangle", "polygon",
                    "angle", "angles", "perimeter", "area", "congruent", "similar", "parallel", "perpendicular", "diagonal"],
        "Trigonometry": ["trigonometry", "trigonometric", "sine", "cosine", "tangent", "sin", "cos", "tan", "sec", "cosec", "cot",
                        "radian", "degree", "hypotenuse"],
        "Calculus": ["calculus", "derivative", "derivatives", "differentiation", "integration", "integral", "integrals", 
                    "limit", "limits", "maxima", "minima", "rate of change", "slope"],
        "Statistics & Probability": ["statistics", "statistical", "probability", "probable", "mean", "median", "mode", 
                                    "average", "data", "frequency", "distribution", "variance", "standard deviation"],
        "Coordinate Geometry": ["coordinate", "coordinates", "cartesian", "graph", "line", "slope", "gradient", "intercept"],
        "Mensuration": ["volume", "volumes", "surface area", "cube", "cuboid", "cylinder", "cone", "sphere", "hemisphere"],
        "Number Systems": ["number system", "number", "numbers", "integer", "integers", "fraction", "fractions", "decimal", 
                          "decimals", "rational", "irrational", "real number", "prime", "composite", "hcf", "lcm"],
        "Set Theory": ["set", "sets", "union", "intersection", "subset", "venn diagram"],
        "Matrices": ["matrix", "matrices", "determinant", "inverse", "transpose"],
        "Sequences & Series": ["sequence", "sequences", "series", "arithmetic progression", "geometric progression", "ap", "gp"],
    }
    
    # Science topics
    science_topics = {
        "Physics - Mechanics": ["force", "motion", "velocity", "acceleration", "momentum", "energy", "work", "power", "friction"],
        "Physics - Electricity": ["current", "voltage", "resistance", "circuit", "electricity", "ohm", "capacitor"],
        "Physics - Optics": ["light", "reflection", "refraction", "lens", "mirror", "optics", "ray", "spectrum"],
        "Chemistry - Organic": ["organic", "hydrocarbon", "alcohol", "acid", "ester", "polymer", "isomer"],
        "Chemistry - Inorganic": ["inorganic", "metal", "non-metal", "periodic", "salt", "oxide", "compound"],
        "Biology - Botany": ["plant", "leaf", "root", "stem", "flower", "photosynthesis", "chlorophyll"],
        "Biology - Zoology": ["animal", "cell", "tissue", "organ", "digestion", "respiration", "circulation"],
    }
    
    # Language topics
    language_topics = {
        "Grammar": ["grammar", "tense", "verb", "noun", "adjective", "adverb", "pronoun", "preposition",
                   "sentence", "clause", "phrase", "subject", "predicate", "punctuation"],
        "Comprehension": ["comprehension", "passage", "read", "understand", "infer", "context", "meaning"],
        "Writing": ["essay", "letter", "write", "composition", "article", "story", "creative writing"],
        "Literature": ["poem", "poetry", "prose", "novel", "drama", "character", "plot", "theme", "author"],
    }
    
    all_topics = {**math_topics, **science_topics, **language_topics}
    
    topic_scores = {}
    for topic, keywords in all_topics.items():
        score = sum(1 for keyword in keywords if keyword in rubric_lower)
        if score > 0:
            topic_scores[topic] = score
    
    if topic_scores:
        best_topic = max(topic_scores, key=topic_scores.get)
        return best_topic
    
    return subject_name
