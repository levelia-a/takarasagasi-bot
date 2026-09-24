import discord

from consts.cooperation import COOP_DEFAULTS, COOP_EVENTS
from services.balance_service import BalanceService
from services.settings_service import SettingsService
from views.common import AdminOnlyModal, AdminOnlyView


def cooperation_settings_text(settings):
    s = COOP_DEFAULTS | settings
    lines = [f"🤝 **VC協力設定：{'ON' if s['coop_enabled'] else 'OFF'}**",
             '同じVCの人間の人数（本人を含む）を開始時に固定します。',
             '各段階は重複せず、到達した最高段階を適用します。']
    for i in (1, 2, 3):
        lines.append(f"段階{i}：{s[f'coop_{i}_people']}人以上 → 探索＋{s[f'coop_{i}_extra']}回 / "
                     f"レア以上の重み×{s[f'coop_{i}_multiplier']/100:g} / イベント{s[f'coop_{i}_chance']/100:g}%")
    lines.append('🎉 イベント当選後の内訳（VCボーナスに追加）：')
    for key in COOP_EVENTS:
        prefix = f'coop_event_{key}'
        name = discord.utils.escape_mentions(discord.utils.escape_markdown(s[f'{prefix}_name']))
        lines.append(f"{name}：{s[f'{prefix}_share']/100:g}% / 探索＋{s[f'{prefix}_extra']}回 / "
                     f"重み×{s[f'{prefix}_multiplier']/100:g} / 成功率＋{s[f'{prefix}_rate']}ポイント")
    lines.extend([
        'イベントは宝探し開始時に1回抽選し、その宝探し全体に適用します。',
        'ステージ補正と掛け合わせます。倍率は当選率そのものの倍率ではありません。',
        '探索回数は合計215回が上限。VC未参加・必要人数未満は通常探索です。',
        '保存後は次の宝探しから適用します。',
    ])
    return '\n'.join(lines)


class CooperationModal(AdminOnlyModal):
    def __init__(self, group, settings):
        event = group in COOP_EVENTS
        title = 'イベント出現割合' if group == 'shares' else 'イベント名・効果設定' if event else f'VC協力：段階{group}'
        super().__init__(title=title)
        self.inputs = []
        fields = [
            (f'coop_event_{key}_share', f'{COOP_EVENTS[key][0]}の割合（%）', 100)
            for key in COOP_EVENTS
        ] if group == 'shares' else [
            (f'coop_event_{group}_name', 'イベント名（40文字まで）', 0),
            (f'coop_event_{group}_extra', '追加探索回数（0〜20）', 1),
            (f'coop_event_{group}_multiplier', 'レア以上の重み倍率（1〜5）', 100),
            (f'coop_event_{group}_rate', '成功率補正（0〜100ポイント）', 1),
        ] if event else [
            (f'coop_{group}_people', '必要人数（2〜100人）', 1),
            (f'coop_{group}_extra', '追加探索回数（0〜20）', 1),
            (f'coop_{group}_multiplier', 'レア以上の重み倍率（1〜5）', 100),
            (f'coop_{group}_chance', 'イベント発生率（0〜100%）', 100),
        ]
        s = COOP_DEFAULTS | settings
        for key, label, scale in fields:
            field = discord.ui.TextInput(label=label, default=s[key] if scale == 0 else f'{s[key]/scale:g}',
                                         max_length=40 if scale == 0 else 8)
            self.inputs.append((key, scale, field))
            self.add_item(field)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            values = {}
            for key, scale, field in self.inputs:
                if scale == 0:
                    values[key] = field.value.strip()
                    continue
                value = BalanceService.scaled_number(field.value)
                if scale == 1:
                    if value % 100:
                        raise ValueError('人数・探索回数・成功率補正は整数で入力してください。')
                    value //= 100
                values[key] = value
            await SettingsService.update(values, interaction.user.id, str(interaction.user), self.title)
        except ValueError as error:
            await interaction.edit_original_response(content=f'❌ {error}')
            return
        await interaction.edit_original_response(content='✅ 保存しました。\n' + cooperation_settings_text(await SettingsService.get_all()))


class CooperationView(AdminOnlyView):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.select(placeholder='変更する協力設定', options=[
        *[discord.SelectOption(label=f'段階{i}の人数・効果・イベント率', value=str(i)) for i in (1, 2, 3)],
        discord.SelectOption(label='イベント4種類の出現割合', value='shares'),
        *[discord.SelectOption(label=f'{info[0]}：名前・効果', value=key) for key, info in COOP_EVENTS.items()],
    ])
    async def choose(self, interaction, select):
        await interaction.response.send_modal(CooperationModal(select.values[0], await SettingsService.get_all()))

    async def set_enabled(self, interaction, enabled):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await SettingsService.update({'coop_enabled': enabled}, interaction.user.id, str(interaction.user), 'VC協力ON/OFF変更')
        await interaction.edit_original_response(content=cooperation_settings_text(await SettingsService.get_all()))

    @discord.ui.button(label='協力ON', style=discord.ButtonStyle.success, row=1)
    async def enable(self, interaction, button):
        await self.set_enabled(interaction, 1)

    @discord.ui.button(label='協力OFF', style=discord.ButtonStyle.secondary, row=1)
    async def disable(self, interaction, button):
        await self.set_enabled(interaction, 0)
