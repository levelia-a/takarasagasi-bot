"""テスト専用の架空データ。本番カタログからは読み込まない。"""

from unittest.mock import patch

from consts.treasure import DIFFICULTIES
from services.treasure_catalog_service import TreasureCatalogService


def catalog_data():
    return {
        difficulty: [
            {"id": f"test_{difficulty}_{i}", "name": f"テスト専用宝物{i}",
             "price": 700 + level * 1000 + i * 100, "probability_percent": "10"}
            for i in range(10)
        ]
        for level, difficulty in enumerate(DIFFICULTIES)
    }


def install_test_catalog(test_case):
    catalog = TreasureCatalogService.validate_catalog(catalog_data())
    test_case.enterContext(patch.object(TreasureCatalogService, "load_catalog", return_value=catalog))
    test_case.enterContext(patch("services.treasure_catalog_service.random.randrange", return_value=0))
    return catalog
