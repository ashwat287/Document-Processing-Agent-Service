from locust import HttpUser, task, between


class DocumentProcessingUser(HttpUser):
    wait_time = between(0.1, 0.5)

    TEST_URLS = [
        "https://arxiv.org/pdf/1706.03762",       # Attention Is All You Need
        "https://arxiv.org/pdf/2005.14165",       # GPT-3
        "https://arxiv.org/pdf/2303.08774",       # GPT-4
        "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf",
        "https://arxiv.org/pdf/1810.04805",       # BERT
    ]

    ANALYSIS_TYPES = ["summary", "extraction", "classification"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._counter = 0

    @task
    def submit_job(self):
        url = self.TEST_URLS[self._counter % len(self.TEST_URLS)]
        analysis = self.ANALYSIS_TYPES[self._counter % len(self.ANALYSIS_TYPES)]
        self._counter += 1

        # Make each submission unique to avoid idempotency dedup
        unique_url = f"{url}?t={self._counter}&u={id(self)}"

        self.client.post("/jobs", json={
            "document_url": unique_url,
            "analysis_type": analysis,
        })

    @task(1)
    def check_health(self):
        self.client.get("/healthz")

    @task(1)
    def check_metrics(self):
        self.client.get("/metrics")
