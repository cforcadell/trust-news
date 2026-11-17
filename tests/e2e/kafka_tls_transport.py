"""Reusable Kafka TLS transport E2E; run inside any kafka-python client pod."""

import os
import uuid
from kafka import KafkaAdminClient, KafkaConsumer, KafkaProducer
from kafka.admin import NewTopic
from kafka.errors import NoBrokersAvailable

bootstrap = os.environ.get('KAFKA_BROKER', 'kafka.infra.svc.cluster.local:9092')
ca = os.environ.get('KAFKA_CA_FILE', '/etc/kafka-tls/ca.crt')
common = dict(bootstrap_servers=bootstrap, security_protocol='SSL', ssl_cafile=ca, ssl_check_hostname=True, api_version_auto_timeout_ms=15000)
topic = os.environ.get('KAFKA_E2E_TOPIC_PREFIX', 's07a_tls_e2e_') + uuid.uuid4().hex[:12]
message = ('s07a:' + uuid.uuid4().hex).encode()
admin = KafkaAdminClient(**common)
try:
    admin.create_topics([NewTopic(name=topic, num_partitions=1, replication_factor=1)])
    producer = KafkaProducer(**common)
    try:
        metadata = producer.send(topic, message).get(timeout=15)
        producer.flush(timeout=15)
        assert metadata.topic == topic
    finally:
        producer.close()
    consumer = KafkaConsumer(topic, group_id='s07a-e2e-' + uuid.uuid4().hex, auto_offset_reset='earliest', consumer_timeout_ms=15000, **common)
    try:
        received = next(iter(consumer)).value
        assert received == message, (received, message)
    finally:
        consumer.close()
    print('tls_produce_consume=PASS topic=' + topic)
    try:
        KafkaAdminClient(bootstrap_servers=bootstrap, security_protocol='PLAINTEXT', api_version_auto_timeout_ms=3000)
    except NoBrokersAvailable:
        print('plaintext_rejected=PASS')
    else:
        raise AssertionError('PLAINTEXT client connected to TLS broker')
finally:
    admin.delete_topics([topic])
    admin.close()
    print('temporary_topic_deleted=' + topic)
