__all__ = ("proxy_connect_cases",)

from foghttp_benchmark.proxy_connect.models import ProxyConnectCase


def proxy_connect_cases() -> dict[str, ProxyConnectCase]:
    return {
        "direct-http": ProxyConnectCase(
            name="direct-http",
            group="http",
            target_scheme="http",
            config="direct",
            description="Direct HTTP baseline through the loopback origin.",
        ),
        "proxy-http": ProxyConnectCase(
            name="proxy-http",
            group="http",
            target_scheme="http",
            config="explicit",
            description="HTTP target through an explicit HTTP proxy.",
        ),
        "trust-env-http": ProxyConnectCase(
            name="trust-env-http",
            group="http",
            target_scheme="http",
            config="trust-env",
            description="HTTP target through environment-derived proxy settings.",
        ),
        "direct-https": ProxyConnectCase(
            name="direct-https",
            group="https",
            target_scheme="https",
            config="direct",
            description="Direct HTTPS baseline with the local benchmark CA.",
        ),
        "proxy-connect": ProxyConnectCase(
            name="proxy-connect",
            group="https",
            target_scheme="https",
            config="explicit",
            description="HTTPS target through explicit HTTP proxy CONNECT.",
        ),
        "trust-env-connect": ProxyConnectCase(
            name="trust-env-connect",
            group="https",
            target_scheme="https",
            config="trust-env",
            description="HTTPS target through environment-derived HTTP proxy CONNECT.",
        ),
        "proxy-connect-cold": ProxyConnectCase(
            name="proxy-connect-cold",
            group="https-cold",
            target_scheme="https",
            config="explicit",
            lifecycle="cold-client",
            description="Short-lived HTTPS CONNECT client path that includes client and tunnel setup.",
        ),
    }
