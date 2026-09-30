"""Persistent vectors; bounded batches and disk ANN, never materialize a corpus in Python."""
from pathlib import Path
from datetime import timedelta
import sys


class VectorIndex:
    @staticmethod
    def bind_empty_dimensions(directory: Path, dimensions: int):
        """Only replace an empty table; never discard previously written vectors."""
        import lancedb
        import pyarrow as pa

        path = directory / "vectors"
        if not path.exists():
            return
        db = lancedb.connect(str(path))
        try:
            table = db.open_table("chunks")
        except FileNotFoundError:
            return
        current = table.schema.field("vector").type.list_size
        if current == dimensions:
            return
        if table.count_rows():
            raise ValueError(f"模型实际返回 {dimensions} 维，已有向量为 {current} 维；请创建新知识库重建索引")
        schema = pa.schema([("id", pa.int64()), ("vector", pa.list_(pa.float32(), dimensions)), ("active", pa.bool_())])
        db.create_table("chunks", schema=schema, mode="overwrite")

    def __init__(self, directory: Path, dimensions: int, *, readonly=False):
        import lancedb
        import pyarrow as pa
        self.db = lancedb.connect(str(directory / "vectors"), read_consistency_interval=timedelta(0))
        schema = pa.schema([("id", pa.int64()), ("vector", pa.list_(pa.float32(), dimensions)), ("active", pa.bool_())])
        self.table = self.db.open_table("chunks") if readonly else self.db.create_table("chunks", schema=schema, exist_ok=True)
        if self.table.schema != schema:
            raise ValueError("向量索引维度或数据结构不一致")

    def put(self, ids, vectors):
        rows = [{"id": key, "vector": vector, "active": False} for key, vector in zip(ids, vectors, strict=True)]
        self.table.merge_insert("id").when_matched_update_all().when_not_matched_insert_all().execute(rows)

    def delete(self, ids):
        if ids:
            self.table.delete("id IN (" + ",".join(str(int(key)) for key in ids) + ")")

    def search(self, vector, limit=150):
        return self.table.search(vector).distance_type("cosine").where("active = true", prefilter=True).select(["id"]).limit(limit).to_list()

    def publish(self, ids):
        self.table.update(where="id IN (" + ",".join(str(int(key)) for key in ids) + ")", values={"active": True})

    def maintain(self):
        count = self.table.count_rows()
        indices = self.table.list_indices()
        if not any("id" in item.columns for item in indices):
            self.table.create_scalar_index("id")
        # Small libraries use exact search; larger ones use an explicitly built IVF index.
        if count >= 256 and not any("vector" in item.columns for item in indices):
            self.table.create_index(metric="cosine", index_type="IVF_FLAT", num_partitions=max(1, min(1024, count // 256)))
        self.table.optimize(cleanup_older_than=timedelta(days=1))

    def count_rows(self):
        return self.table.count_rows()


# Android has no LanceDB/PyArrow distribution. Select its storage explicitly;
# dependency errors on other platforms must still surface.
if sys.platform == "android":
    from .vectors_sqlite import SQLiteVectorIndex as VectorIndex
