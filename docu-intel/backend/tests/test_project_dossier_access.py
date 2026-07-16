from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.base import Base
from app.models import Document, DocumentAccessMetadata, HotelChain
from app.models.project import DocumentOccurrence, Project
from app.services.project_dossier import get_project_dossier, list_project_documents
from app.services.tenant_access import AccessScope


def _scope(chain_id: int, *, prices: bool = False) -> AccessScope:
    return AccessScope(
        principal_type="user", principal_id="test", chain_ids={chain_id}, can_view_prices=prices
    )


def test_dossier_and_document_list_filter_each_occurrence_before_returning_data():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    chain_a, chain_b = HotelChain(name="A"), HotelChain(name="B")
    session.add_all([chain_a, chain_b])
    session.flush()
    project = Project(year=2025, brand_id=chain_a.id, name="Proyecto A")
    visible = Document(original_filename="a.pdf", file_hash="a", source_path="/a.pdf")
    hidden = Document(original_filename="b.pdf", file_hash="b", source_path="/b.pdf")
    session.add_all([project, visible, hidden])
    session.flush()
    session.add_all([
        DocumentAccessMetadata(document_id=visible.id, chain_id=chain_a.id, assignment_status="assigned", assignment_source="test", tags_json=[]),
        DocumentAccessMetadata(document_id=hidden.id, chain_id=chain_b.id, assignment_status="assigned", assignment_source="test", tags_json=[]),
        DocumentOccurrence(document_id=visible.id, source_path="/a.pdf", source_root="/", year=2025, brand_id=chain_a.id, project_id=project.id, original_filename="a.pdf", category="facturas"),
        DocumentOccurrence(document_id=hidden.id, source_path="/b.pdf", source_root="/", year=2025, brand_id=chain_b.id, project_id=project.id, original_filename="b.pdf", category="facturas"),
    ])
    session.commit()

    dossier = get_project_dossier(session, project.id, access_scope=_scope(chain_a.id))
    documents = list_project_documents(session, project.id, access_scope=_scope(chain_a.id))

    assert dossier.total_documents == 1
    assert dossier.participant_count == 0
    payload = dossier.to_dict()
    assert payload["sources"] == [
        {"project_id": project.id, "kind": "project"},
        {"document_id": visible.id, "filename": "a.pdf", "kind": "document"},
    ]
    assert "financials" in payload["data_gaps"]
    assert [row["filename"] for row in documents] == ["a.pdf"]
    assert documents[0]["source_path"] is None
