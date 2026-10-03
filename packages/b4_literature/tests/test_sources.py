from urllib.parse import parse_qs, urlparse

from b4_literature.sources import EuropePmcSource


def test_europe_pmc_adapter_is_bounded_and_skips_records_without_abstracts() -> None:
    seen: dict = {}

    def transport(url: str, timeout: float) -> dict:
        seen.update(url=url, timeout=timeout)
        return {
            "resultList": {
                "result": [
                    {
                        "doi": "10.1000/example",
                        "pmid": "1234",
                        "title": "Nisin activity",
                        "abstractText": "Nisin inhibited Listeria.",
                        "authorString": "A Author, B Author",
                        "pubYear": "2024",
                    },
                    {"pmid": "missing", "title": "No abstract"},
                ]
            }
        }

    documents = EuropePmcSource(transport).search("nisin listeria", 7, 4.5)
    params = parse_qs(urlparse(seen["url"]).query)
    assert params["pageSize"] == ["7"]
    assert params["resultType"] == ["core"]
    assert seen["timeout"] == 4.5
    assert len(documents) == 1
    assert documents[0].source.source_id == "doi:10.1000/example"
