"use strict";

exports.config = {
  app_name: [process.env.NEW_RELIC_APP_NAME || "job-search-web"],
  license_key: process.env.NEW_RELIC_LICENSE_KEY,
  distributed_tracing: {
    enabled: true,
  },
  logging: {
    enabled: true,
    level: process.env.NEW_RELIC_LOG_LEVEL || "info",
  },
  application_logging: {
    enabled: process.env.NEW_RELIC_APPLICATION_LOGGING_ENABLED !== "false",
    forwarding: {
      enabled: process.env.NEW_RELIC_APPLICATION_LOGGING_FORWARDING_ENABLED !== "false",
    },
    local_decorating: {
      enabled: process.env.NEW_RELIC_APPLICATION_LOGGING_LOCAL_DECORATING_ENABLED === "true",
    },
  },
  allow_all_headers: true,
  attributes: {
    exclude: [
      "request.headers.cookie",
      "request.headers.authorization",
      "request.headers.proxyAuthorization",
      "request.headers.setCookie*",
      "request.headers.x*",
      "response.headers.cookie",
      "response.headers.authorization",
      "response.headers.proxyAuthorization",
      "response.headers.setCookie*",
      "response.headers.x*",
    ],
  },
};
