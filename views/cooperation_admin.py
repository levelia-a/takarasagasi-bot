import discord

from consts.cooperation import COOP_DEFAULTS
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
    lines.extend([
        f"🎉 イベント当選時：さらに探索＋{s['coop_event_extra']}回 / 重み×{s['coop_event_multiplier']/100:g}",
        'イベントは宝探し開始時に1回抽選し、その宝探し全体に適用します。',
        '色補正と掛け合わせます。倍率は当選率そのものの倍率ではありません。',
        '探索回数は合計215回が上限。VC未参加・必要人数未満は通常探索です。',
        '保存後は次の宝探しから適用します。',
    ])
    return '\n'.join(lines)


class CooperationModal(AdminOnlyModal):
    def __init__(self, group, settings):
        event = group == 'event'
        super().__init__(title='協力イベント設定' if event else f'VC協力：段階{group}')
        self.inputs = []
        fields = [('coop_event_extra', 'イベント追加探索回数（0〜20）', 1),
                  ('coop_event_multiplier', 'イベント重み倍率（1〜5）', 100)] if event else [
            (f'coop_{group}_people', '必要人数（2〜100人）', 1),
            (f'coop_{group}_extra', '追加探索回数（0〜20）', 1),
            (f'coop_{group}_multiplier', 'レア以上の重み倍率（1〜5）', 100),
            (f'coop_{group}_chance', 'イベント発生率（0〜100%）', 100),
        ]
        s = COOP_DEFAULTS | settings
        for key, label, scale in fields:
            field = discord.ui.TextInput(label=label, default=f'{s[key]/scale:g}', max_length=8)
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
                        raise ValueError('人数と探索回数は整数で入力してください。')
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
        discord.SelectOption(label='イベント当選時の追加効果', value='event'),
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
