import os
import sys
import logging
from kafka.admin import KafkaAdminClient, NewTopic

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from common.utils.logging_utils import configure_single_line_json_logging

log_level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
configure_single_line_json_logging(log_level)
logger = logging.getLogger("news-handler-kafka-init")

KAFKA_BROKER = os.getenv("KAFKA_BROKER", "kafka:9092")
TOPIC_REQUESTS = os.getenv("TOPIC_REQUESTS", "fake_news_requests")
TOPIC_RESPONSES = os.getenv("TOPIC_RESPONSES", "fake_news_responses")
TOPIC_LIGHT_VALIDATION_REQUESTS = os.getenv("TOPIC_LIGHT_VALIDATION_REQUESTS", "trustnews.validation.requests")
TOPIC_LIGHT_VALIDATION_RESPONSES = os.getenv("TOPIC_LIGHT_VALIDATION_RESPONSES", "trustnews.validation.responses")

def create_topics():
    admin_client = KafkaAdminClient(
        bootstrap_servers=KAFKA_BROKER
    )

    topics = [
        NewTopic(name=TOPIC_REQUESTS, num_partitions=1, replication_factor=1),
        NewTopic(name=TOPIC_RESPONSES, num_partitions=1, replication_factor=1),
        NewTopic(name=TOPIC_LIGHT_VALIDATION_REQUESTS, num_partitions=3, replication_factor=1),
        NewTopic(name=TOPIC_LIGHT_VALIDATION_RESPONSES, num_partitions=3, replication_factor=1)
    ]

    try:
        admin_client.create_topics(new_topics=topics, validate_only=False)
        logger.info('Kafka topics created or already exist, including LIGHT validation topics.')
    except Exception as e:
        logger.exception(f"Error creating topics: {e}")
    finally:
        admin_client.close()

if __name__ == "__main__":
    create_topics()
