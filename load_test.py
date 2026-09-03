from locust import HttpUser, task, between
import random

QUERIES = [
    "Design an AWS architecture for an e-commerce platform expecting 100k concurrent users during Black Friday.",
    "Build a real-time video streaming service for 1 million daily active users with low latency requirements.",
    "Design a machine learning pipeline that processes 10TB of data daily with cost under $5000/month.",
    "Create a ride sharing app backend that handles 50k concurrent drivers and riders across 10 cities.",
    "Design a social media platform with image uploads, news feed, and push notifications for 500k users."
]

class ArchitectureUser(HttpUser):
    wait_time = between(1, 3)

    @task
    def analyze(self):
        query = random.choice(QUERIES)
        self.client.post("/analyze", json={"query": query})