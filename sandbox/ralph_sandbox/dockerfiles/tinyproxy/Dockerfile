ARG IMAGE_TAG=latest
FROM ai-agents-sandbox/tinyproxy-base:${IMAGE_TAG}

COPY sandbox/ralph_sandbox/dockerfiles/common-settings/default-whitelist.txt /etc/tinyproxy/default-whitelist.txt
COPY sandbox/ralph_sandbox/dockerfiles/tinyproxy/tinyproxy.conf /etc/tinyproxy/tinyproxy.conf.default
COPY sandbox/ralph_sandbox/dockerfiles/tinyproxy/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh && \
    chown -R tinyproxy:tinyproxy /etc/tinyproxy && \
    chmod 755 /etc/tinyproxy
USER tinyproxy

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]