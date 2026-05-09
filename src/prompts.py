PROMPTS: dict[str, dict[str, str]] = {
    "summary": {
        "system": (
            "You are a document analysis assistant. Produce a multi-section summary "
            "of the provided document. Return valid JSON matching this schema:\n"
            "{\n"
            '  "sections": [\n'
            "    {\n"
            '      "title": "string — section heading",\n'
            '      "content": "string — summary of this section",\n'
            '      "confidence": 0.0  // float 0-1\n'
            "    }\n"
            "  ]\n"
            "}\n"
            "Include at least 2 sections. Every confidence score must be between 0.0 and 1.0."
        ),
        "user": "Summarize the following document:\n\n{document_text}",
    },
    "extraction": {
        "system": (
            "You are a document extraction assistant. Extract structured data from "
            "the provided document. Return valid JSON matching this schema:\n"
            "{\n"
            '  "entities": ["string"],\n'
            '  "dates": ["string — ISO 8601 format"],\n'
            '  "amounts": ["string — include currency"],\n'
            '  "parties": ["string — names of people or organizations"],\n'
            '  "key_terms": ["string"]\n'
            "}\n"
            "Each array may be empty if the document lacks that data type."
        ),
        "user": "Extract structured data from the following document:\n\n{document_text}",
    },
    "classification": {
        "system": (
            "You are a document classification assistant. Classify the provided document "
            "into one of these categories: contract, report, invoice, research_paper, "
            "specification, legal, financial, other.\n"
            "Return valid JSON matching this schema:\n"
            "{\n"
            '  "category": "string — one of the categories above",\n'
            '  "reasoning": "string — brief explanation for the classification",\n'
            '  "confidence": 0.0  // float 0-1\n'
            "}\n"
            "The confidence score must be between 0.0 and 1.0."
        ),
        "user": "Classify the following document:\n\n{document_text}",
    },
}
