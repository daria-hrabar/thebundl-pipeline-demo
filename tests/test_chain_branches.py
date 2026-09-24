from thebundl.config import Settings
from thebundl.schemas import DealCandidate, ExtractedPage
from thebundl.validation import validate_with_branch_pages


def offer(text='Bite Cafe offers 20% off lunch at all locations.'):
    return DealCandidate(business_name='Bite Cafe', address='', title='20% off lunch',
        description='20% off lunch', evidence_text=text, source_url='https://food.test/offer')


def branch(address='55 Lexington Ave', latitude=40.7406, name='Bite Cafe'):
    return ExtractedPage(source_url='https://food.test/branches', text='', structured_data=[{
        'name': name, 'address': {'streetAddress': address},
        'geo': {'latitude': latitude, 'longitude': -73.9832}}])


def validate(candidate, pages):
    return validate_with_branch_pages(candidate, ExtractedPage(source_url=candidate.source_url,
        text=candidate.evidence_text), pages, Settings(_env_file=None).campuses)


def test_chain_offer_uses_separate_nearby_branches_and_retains_provenance():
    results = validate(offer(), [branch(), branch('99 Lexington Ave'), branch('Distant', 0)])
    assert len(results) == 2 and all(result.accepted for result in results)
    assert len({result.candidate.fingerprint for result in results}) == 2
    assert all(result.branch_evidence_urls == ['https://food.test/branches'] for result in results)
    assert all(result.candidate.evidence_text == offer().evidence_text for result in results)


def test_chain_offer_does_not_infer_participation_or_branch_identity():
    for text in ('Bite Cafe offers 20% off lunch.',
                 'Bite Cafe offers 20% off lunch at all locations except airport stores.',
                 'Bite Cafe offers 20% off lunch at participating locations.'):
        assert not validate(offer(text), [branch()])[0].accepted
    assert not validate(offer(), [branch(name='Another Cafe')])[0].accepted
    assert not validate(offer(), [branch(latitude=0)])[0].accepted
    assert not validate(offer(), [branch(), branch(latitude=41)])[0].accepted
    assert not validate(offer(), [])[0].accepted
