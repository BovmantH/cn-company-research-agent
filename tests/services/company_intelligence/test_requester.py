from backend.services.company_intelligence.requester import resolve_client_ip


def test_untrusted_peer_cannot_spoof_forwarded_for() -> None:
    assert resolve_client_ip(
        peer_ip="203.0.113.10",
        forwarded_for="198.51.100.20",
        trusted_proxy_cidrs=("10.0.0.0/8",),
    ) == "203.0.113.10"


def test_trusted_proxy_chain_uses_first_untrusted_hop_from_right() -> None:
    assert resolve_client_ip(
        peer_ip="10.0.0.2",
        forwarded_for="198.51.100.20, 10.0.0.1",
        trusted_proxy_cidrs=("10.0.0.0/8",),
    ) == "198.51.100.20"


def test_invalid_forwarded_for_falls_back_to_peer() -> None:
    assert resolve_client_ip(
        peer_ip="10.0.0.2",
        forwarded_for="not-an-ip, 10.0.0.1",
        trusted_proxy_cidrs=("10.0.0.0/8",),
    ) == "10.0.0.2"


def test_non_ip_test_peer_is_stable_and_never_trusts_forwarded_header() -> None:
    assert resolve_client_ip(
        peer_ip="testclient",
        forwarded_for="198.51.100.20",
        trusted_proxy_cidrs=("0.0.0.0/0",),
    ) == "testclient"
