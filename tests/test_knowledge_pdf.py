from pathlib import Path
import threading

from src.knowledge.contracts import LibraryConfig
from src.knowledge.parser import passages


def minimal_pdf(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 40 700 Td ({text}) Tj ET".encode('ascii')
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
               b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"]
    data, offsets = b"%PDF-1.4\n", [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(data)
    data += b"xref\n0 6\n0000000000 65535 f \n"
    data += b"".join(f"{offset:010} 00000 n \n".encode() for offset in offsets[1:])
    data += f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return data


def test_pdf_text_keeps_page_citation_and_reports_blank_pages(tmp_path):
    config = LibraryConfig(name="PDF", folder=str(tmp_path), embedding_url="http://localhost/v1/embeddings",
                           embedding_model="test", dimensions=8)
    path = tmp_path / 'paper.pdf'
    path.write_bytes(minimal_pdf("Feline knowledge from a research paper."))
    warnings = []
    chunks = list(passages(path, config, threading.Event(), warnings))
    assert chunks[0].page == 1 and chunks[0].line is None
    assert 'Feline knowledge' in chunks[0].text
    assert warnings == []
    path.write_bytes(minimal_pdf(""))
    assert list(passages(path, config, threading.Event(), warnings)) == []
    assert 'OCR' in warnings[0]
