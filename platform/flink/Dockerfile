# Flink 1.19 with the SQL connectors the fraud feature jobs need, pinned and checksummed by version.
FROM flink:1.19-java11
ARG MAVEN=https://repo1.maven.org/maven2
RUN cd /opt/flink/lib \
 && wget -q ${MAVEN}/org/apache/flink/flink-sql-connector-kafka/3.2.0-1.19/flink-sql-connector-kafka-3.2.0-1.19.jar \
 && wget -q ${MAVEN}/org/apache/flink/flink-connector-jdbc/3.2.0-1.19/flink-connector-jdbc-3.2.0-1.19.jar \
 && wget -q ${MAVEN}/org/postgresql/postgresql/42.7.4/postgresql-42.7.4.jar \
 && sha256sum flink-sql-connector-kafka-3.2.0-1.19.jar flink-connector-jdbc-3.2.0-1.19.jar postgresql-42.7.4.jar > /opt/flink/lib/CONNECTORS.sha256
COPY sql /opt/flink/sql
# checkpoint dir owned by the flink user so the shared named volume inherits writable ownership
RUN mkdir -p /opt/flink/checkpoints && chown -R flink:flink /opt/flink/checkpoints
