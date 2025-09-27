import os
from kafka.admin import KafkaAdminClient, NewTopic

KAFKA_BROKER = os.getenv("KAFKA_BROKER", "kafka:9092")
TOPIC_REQUESTS = os.getenv("TOPIC_REQUESTS", "fake_news_requests")
TOPIC_RESPONSES = os.getenv("TOPIC_RESPONSES", "fake_news_responses")

def create_topics():
    admin_client = KafkaAdminClient(
        bootstrap_servers=KAFKA_BROKER
    )

    topics = [
        NewTopic(name=TOPIC_REQUESTS, num_partitions=1, replication_factor=1),
        NewTopic(name=TOPIC_RESPONSES, num_partitions=1, replication_factor=1)
    ]

    try:
        admin_client.create_topics(new_topics=topics, validate_only=False)
        print(f"Topics '{TOPIC_REQUESTS}' and '{TOPIC_RESPONSES}' created (or already exist).")
    except Exception as e:
        print(f"Error creating topics: {e}")
    finally:
        admin_client.close()

if __name__ == "__main__":
    create_topics()
