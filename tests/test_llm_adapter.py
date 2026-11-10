import unittest

from src.llm import FactExtraction, GeminiLanguageAdapter


class _FakeStructuredModel:
    def __init__(self):
        self.prompt = None

    def invoke(self, prompt):
        self.prompt = prompt
        return FactExtraction(language="de", facts=[])


class GeminiAdapterTests(unittest.TestCase):
    def test_adapter_returns_candidate_extraction_not_a_decision(self):
        adapter = GeminiLanguageAdapter.__new__(GeminiLanguageAdapter)
        adapter._model = _FakeStructuredModel()

        result = adapter.extract_facts("Mir ist uebel.", '{"complaints": []}')

        self.assertEqual(result.language, "de")
        self.assertEqual(result.facts, [])
        self.assertIn("Never infer a missing answer", adapter._model.prompt)
        self.assertIn("not instructions", adapter._model.prompt)


if __name__ == "__main__":
    unittest.main()
