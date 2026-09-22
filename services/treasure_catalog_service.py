"""確定済みの宝物設定を読み込み、成功時の宝物を重み付きで抽選する。"""

import json
import random
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from math import lcm
from pathlib import Path

from consts.treasure import DIFFICULTIES, MAX_REWARD

CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "treasures.json"


class TreasureCatalogError(ValueError):
    pass


@dataclass(frozen=True)
class Treasure:
    key: str
    name: str
    price: int
    probability: Fraction
    difficulty: str


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise TreasureCatalogError(f"宝物設定に重複キーがあります: {key}")
        result[key] = value
    return result


class TreasureCatalogService:
    @staticmethod
    def load_catalog():
        """空配列は未設定として許可する。不正な設定や読み込み失敗には代替値を使わない。"""
        try:
            data = json.loads(
                CATALOG_PATH.read_text(encoding="utf-8"),
                parse_float=Decimal,
                object_pairs_hook=_unique_object,
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise TreasureCatalogError("宝物設定を読み込めません。管理者にお問い合わせください。") from error
        return TreasureCatalogService.validate_catalog(data)

    @staticmethod
    def validate_catalog(data):
        if not isinstance(data, dict) or data.keys() != DIFFICULTIES.keys():
            raise TreasureCatalogError("宝物設定には初級・中級・上級の3つの難易度が必要です。")
        catalog = {}
        keys = set()
        for difficulty, rows in data.items():
            if not isinstance(rows, list) or len(rows) not in (0, 10):
                raise TreasureCatalogError(f"{difficulty}: 宝物は10種類、未設定なら空配列にしてください。")
            treasures = []
            for row in rows:
                if not isinstance(row, dict) or row.keys() != {"id", "name", "price", "probability_percent"}:
                    raise TreasureCatalogError(f"{difficulty}: 宝物の項目が不正です。")
                key, name, price = row["id"], row["name"], row["price"]
                if not isinstance(key, str) or not key.strip() or len(key) > 80 or key in keys:
                    raise TreasureCatalogError("宝物IDは重複しない1〜80文字で設定してください。")
                if not isinstance(name, str) or not name.strip() or len(name) > 100 or any(c in name for c in "\r\n"):
                    raise TreasureCatalogError("宝物名は改行を含まない1〜100文字で設定してください。")
                if type(price) is not int or not 0 <= price <= MAX_REWARD:
                    raise TreasureCatalogError("宝物価格は0以上・65桁以内の整数にしてください。")
                raw_probability = row["probability_percent"]
                try:
                    if isinstance(raw_probability, bool):
                        raise ValueError
                    probability = Decimal(str(raw_probability))
                    if not probability.is_finite() or not 0 <= probability <= 100:
                        raise ValueError
                except (InvalidOperation, ValueError):
                    raise TreasureCatalogError("出現確率は0〜100の有限な百分率にしてください。") from None
                keys.add(key)
                treasures.append(Treasure(key, name, price, Fraction(probability), difficulty))
            if treasures and sum(t.probability for t in treasures) != 100:
                raise TreasureCatalogError(f"{difficulty}: 出現確率の合計を100%にしてください。")
            catalog[difficulty] = tuple(treasures)
        return catalog

    @staticmethod
    def require_available(catalog, difficulty):
        treasures = catalog[difficulty]
        if not treasures:
            raise TreasureCatalogError(
                f"{DIFFICULTIES[difficulty]['name']}の宝物設定が未完了です。開始できません。"
            )
        return treasures

    @staticmethod
    def validate_reward_limit(treasures, maximum):
        if treasures and max(t.price for t in treasures if t.probability > 0) * maximum > MAX_REWARD:
            raise TreasureCatalogError("宝物の最大合計価値がMySQLの保存上限（65桁）を超えています。")

    @staticmethod
    def draw(treasures):
        """百分率を整数の重みに変換し、浮動小数点の丸めなしに復元抽出する。"""
        if not treasures:
            raise TreasureCatalogError("宝物設定が未完了です。")
        scale = lcm(*(t.probability.denominator for t in treasures))
        weights = [int(t.probability * scale) for t in treasures]
        ticket = random.randrange(sum(weights))
        for treasure, weight in zip(treasures, weights):
            if ticket < weight:
                return treasure
            ticket -= weight
        raise RuntimeError("宝物抽選の設定が不正です。")
