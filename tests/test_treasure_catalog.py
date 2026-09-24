import json
import unittest
from decimal import Decimal
from unittest.mock import patch

from consts.treasure import DEFAULT_SETTINGS, MAX_REWARD
from services.settings_service import SettingsService
from services.treasure_catalog_service import (
    CATALOG_PATH, TreasureCatalogError, TreasureCatalogService,
)
from tests.treasure_fixtures import catalog_data


class CatalogTests(unittest.TestCase):
    def test_empty_difficulties_cannot_start(self):
        catalog = TreasureCatalogService.validate_catalog(
            {difficulty: [] for difficulty in catalog_data()}
        )
        for difficulty in catalog:
            with self.assertRaises(TreasureCatalogError):
                TreasureCatalogService.require_available(catalog, difficulty)

    def test_exact_decimal_weights_and_boundaries_by_difficulty(self):
        data = catalog_data()
        for rows in data.values():
            for row in rows:
                row["probability_percent"] = 0
            rows[0]["probability_percent"] = Decimal("0.1")
            rows[1]["probability_percent"] = Decimal("99.9")
        catalog = TreasureCatalogService.validate_catalog(data)
        for difficulty, pool in catalog.items():
            for ticket, index in ((0, 0), (1, 1), (999, 1)):
                with self.subTest(difficulty=difficulty, ticket=ticket):
                    with patch("services.treasure_catalog_service.random.randrange", return_value=ticket) as draw:
                        self.assertEqual(TreasureCatalogService.draw(pool), pool[index])
                        draw.assert_called_once_with(1000)
                    self.assertEqual(pool[index].difficulty, difficulty)

    def test_invalid_rows_are_rejected(self):
        for field, value in (
            ("id", ""), ("name", "x\ny"), ("name", "x" * 101),
            ("price", -1), ("price", True), ("price", 1.5),
            ("price", MAX_REWARD + 1), ("probability_percent", True),
            ("probability_percent", "NaN"), ("probability_percent", "Infinity"),
            ("probability_percent", -1), ("probability_percent", 101),
            ("probability_percent", None), ("probability_percent", "9.9"),
        ):
            with self.subTest(field=field, value=value):
                data = catalog_data()
                data["beginner"][0][field] = value
                with self.assertRaises(TreasureCatalogError):
                    TreasureCatalogService.validate_catalog(data)

    def test_count_keys_and_duplicate_ids_are_rejected(self):
        for mutation in (
            lambda data: data.pop("advanced"),
            lambda data: data["beginner"].pop(),
            lambda data: data["beginner"][0].update(extra=True),
            lambda data: data["advanced"][0].update(id=data["beginner"][0]["id"]),
        ):
            data = catalog_data()
            mutation(data)
            with self.assertRaises(TreasureCatalogError):
                TreasureCatalogService.validate_catalog(data)

    def test_load_errors_do_not_use_fallback(self):
        for source in ('{"beginner": [], "beginner": []}', '{', '[]'):
            with patch.object(type(CATALOG_PATH), "read_text", return_value=source):
                with self.assertRaises(TreasureCatalogError):
                    TreasureCatalogService.load_catalog()
        with patch.object(type(CATALOG_PATH), "read_text", side_effect=OSError):
            with self.assertRaises(TreasureCatalogError):
                TreasureCatalogService.load_catalog()

    def test_json_decimal_probabilities_are_exact(self):
        data = catalog_data()
        for rows in data.values():
            rows[0]["probability_percent"] = 0.1
            rows[1]["probability_percent"] = 19.9
        with patch.object(type(CATALOG_PATH), "read_text", return_value=json.dumps(data)):
            catalog = TreasureCatalogService.load_catalog()
        self.assertEqual(sum(t.probability for t in catalog["beginner"]), 100)

    def test_reward_limit_uses_treasures_not_entry_price(self):
        data = catalog_data()
        catalog = TreasureCatalogService.validate_catalog(data)
        SettingsService.validate_settings(DEFAULT_SETTINGS | {"beginner_price": MAX_REWARD}, catalog)
        data["beginner"][0]["price"] = MAX_REWARD // 5
        catalog = TreasureCatalogService.validate_catalog(data)
        SettingsService.validate_settings(DEFAULT_SETTINGS | {'coop_enabled': 0}, catalog)
        with self.assertRaises(TreasureCatalogError):
            SettingsService.validate_settings(DEFAULT_SETTINGS | {"beginner_max": 6, 'coop_enabled': 0}, catalog)
