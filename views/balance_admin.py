import discord

from consts.rarity import RARITIES
from consts.stages import STAGES
from consts.treasure import DIFFICULTIES
from services.balance_service import BalanceService
from services.settings_service import SettingsService
from services.treasure_catalog_service import TreasureCatalogService
from views.common import AdminOnlyModal, AdminOnlyView


GROUPS = {
    'map_chance': ('地図の出現率（%）', [(f'map_{t}_chance', n, 100) for t, n in [('copper', '銅'), ('silver', '銀'), ('gold', '金')]]),
    'map_bonus': ('地図の成功率補正（ポイント）', [(f'map_{t}_bonus', n, 1) for t, n in [('copper', '銅'), ('silver', '銀'), ('gold', '金')]]),
    'stage_chance': ('開始ステージの出現率（%）', [(f'stage_{key}_chance', info['name'], 100) for key, info in STAGES.items()]),
    'stage_multiplier': ('ステージ別レア以上の抽選倍率', [(f'stage_{key}_multiplier', info['name'], 100) for key, info in STAGES.items()]),
    'rarity_chance': ('レア度の基本配分（%）', [(f'rarity_{r}_chance', n, 100) for r, n in RARITIES.items()]),
}


def balance_text(settings):
    lines = ['⚙️ **地図・ステージ・レア設定**', '変更は次の宝探しから適用されます。ステージは開始時に抽選し、終了まで固定します。', '']
    for group, (title, fields) in GROUPS.items():
        lines.append(f"**{title}**")
        lines.append(' / '.join(f'{name}：{settings[key] / scale:g}' for key, name, scale in fields))
        if group == 'map_chance':
            normal = 100 - sum(settings[key] / scale for key, _, scale in fields)
            lines.append(f'通常の地図：残りの{normal:g}%')
        if group == 'rarity_chance':
            lines.append('適用中' if settings['rarity_profile_enabled'] else '未適用（宝物ごとの出現率を使用）。保存すると適用されます。')
    lines.append('\n倍率はレア以上の抽選の重みです。当選率がそのまま倍になる意味ではありません。')
    lines.append('宝物設定では難易度ごとに10種類の出現率・レア度を編集できます。')
    return '\n'.join(lines)


class BalanceModal(AdminOnlyModal):
    def __init__(self, group, settings):
        title, fields = GROUPS[group]
        super().__init__(title=title)
        self.group = group
        self.inputs = []
        for key, label, scale in fields:
            field = discord.ui.TextInput(label=label, default=f'{settings[key] / scale:g}', max_length=8)
            self.inputs.append((key, scale, field))
            self.add_item(field)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            values = {}
            for key, scale, field in self.inputs:
                value = BalanceService.scaled_number(field.value)
                if scale == 1:
                    if value % 100:
                        raise ValueError('成功率補正は整数ポイントで入力してください。')
                    value //= 100
                values[key] = value
            if self.group == 'rarity_chance':
                values['rarity_profile_enabled'] = 1
            await SettingsService.update(values, interaction.user.id, str(interaction.user), self.title)
        except ValueError as error:
            await interaction.edit_original_response(content=f'❌ {error}')
            return
        await interaction.edit_original_response(content='✅ 保存しました。\n' + balance_text(await SettingsService.get_all()))


class TreasureBalanceModal(AdminOnlyModal):
    def __init__(self, difficulty, pool, settings):
        super().__init__(title=f'{DIFFICULTIES[difficulty]["name"]}：宝物の出現率・レア度')
        self.difficulty = difficulty
        # 基本確率を編集する。レア度配分による正規化後の値を逆書きしない。
        pool = BalanceService.apply_catalog({difficulty: pool}, settings | {'rarity_profile_enabled': 0})[difficulty]
        self.pool = pool
        probabilities = settings.get(f'treasure_{difficulty}_probabilities', '').split(',')
        if probabilities == ['']:
            # 元カタログは小数第2位より細かい値も許容する。入力時に明示的に検証する。
            probabilities = [str(float(t.probability)) for t in pool]
        self.chances = discord.ui.TextInput(
            label='出現率%：宝物順に10行、合計100%', style=discord.TextStyle.paragraph,
            default='\n'.join(probabilities), max_length=240,
        )
        self.rarities = discord.ui.TextInput(
            label='レア度：同じ順に10行（ノーマル等）', style=discord.TextStyle.paragraph,
            default='\n'.join(RARITIES[t.rarity] for t in pool), max_length=240,
        )
        self.add_item(self.chances)
        self.add_item(self.rarities)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            chances = [line.strip() for line in self.chances.value.strip().splitlines()]
            rarities = [line.strip() for line in self.rarities.value.strip().splitlines()]
            if len(chances) != 10 or len(rarities) != 10:
                raise ValueError('出現率・レア度をそれぞれ10行入力してください。')
            values = [BalanceService.scaled_number(v) for v in chances]
            names = {name: key for key, name in RARITIES.items()}
            rarities = [names.get(v, v) for v in rarities]
            await SettingsService.update({
                f'treasure_{self.difficulty}_probabilities': ','.join(f'{v / 100:g}' for v in values),
                f'treasure_{self.difficulty}_rarities': ','.join(rarities),
            }, interaction.user.id, str(interaction.user), self.title)
        except ValueError as error:
            await interaction.edit_original_response(content=f'❌ {error}')
            return
        await interaction.edit_original_response(content='✅ 宝物設定を保存しました。次の宝探しから適用されます。')


class TreasureBalanceView(AdminOnlyView):
    def __init__(self, difficulty):
        super().__init__(timeout=300)
        self.difficulty = difficulty

    @discord.ui.button(label='出現率・レア度を編集', style=discord.ButtonStyle.primary)
    async def edit(self, interaction, button):
        settings = await SettingsService.get_all()
        pool = TreasureCatalogService.load_catalog()[self.difficulty]
        if not pool:
            await interaction.response.send_message('宝物ファイルが未設定です。', ephemeral=True)
            return
        await interaction.response.send_modal(TreasureBalanceModal(self.difficulty, pool, settings))


class BalanceView(AdminOnlyView):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.select(placeholder='変更する項目を選択', options=[
        *[discord.SelectOption(label=title, value=key) for key, (title, _) in GROUPS.items()],
        *[discord.SelectOption(label=f'{info["name"]}の宝物設定', value=f'treasure:{key}') for key, info in DIFFICULTIES.items()],
    ])
    async def select_setting(self, interaction, select):
        key = select.values[0]
        settings = await SettingsService.get_all()
        if key in GROUPS:
            await interaction.response.send_modal(BalanceModal(key, settings))
            return
        difficulty = key.split(':', 1)[1]
        await interaction.response.defer(ephemeral=True, thinking=True)
        catalog = BalanceService.apply_catalog(TreasureCatalogService.load_catalog(), settings)
        pool = catalog[difficulty]
        if not pool:
            await interaction.edit_original_response(content='宝物ファイルが未設定です。先に10種類を設定してください。')
            return
        lines = [f'{i}. {discord.utils.escape_markdown(t.name[:50])}{"…" if len(t.name) > 50 else ""}【{RARITIES[t.rarity]}】 {float(t.probability):.2f}%'
                 for i, t in enumerate(pool, 1)]
        await interaction.edit_original_response(
            content='宝物の入力順（表示はレア度配分適用後の基本確率）\n' + '\n'.join(lines),
            view=TreasureBalanceView(difficulty), allowed_mentions=discord.AllowedMentions.none(),
        )

    @discord.ui.button(label='レア度配分を解除（宝物個別の確率へ）', style=discord.ButtonStyle.secondary, row=1)
    async def disable_rarity_profile(self, interaction, button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await SettingsService.update({'rarity_profile_enabled': 0}, interaction.user.id, str(interaction.user), 'レア度配分解除')
        await interaction.edit_original_response(content='✅ 解除しました。\n' + balance_text(await SettingsService.get_all()))
