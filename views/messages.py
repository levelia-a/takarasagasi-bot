import discord

from consts.treasure import DIFFICULTIES, RESULT_NAMES, TEST_MODES
from consts.maps import MAPS
from consts.rarity import RARITIES, EXPLORATION_COLORS


def cooperation_text(session):
    bonus = session.cooperation
    if not bonus.tier:
        return '\n\n🤝 VC協力ボーナスなし（開始時判定）'
    text = (f'\n\n🤝 **VC協力：開始時{bonus.people}人**\n'
            f'探索＋{bonus.extra}回 / レア以上の重み×{float(bonus.multiplier):g}\n'
            'この宝探し全体に適用（色補正と掛け合わせ）')
    if bonus.event:
        text += '\n🎉 **協力探索イベント発生！**（上記はイベント効果込み）'
    return text


def exploration_embed(session):
    current = MAPS[session.map_tier]
    bonus = EXPLORATION_COLORS[session.exploration_color]
    color = bonus['color']
    description = exploration_text(session)
    description += f"\n\n🗺️ 使用地図：{current['name']}\n🎯 今回の成功率：{session.rate}%"
    description += f"\n🎨 今回の探索色：{bonus['name']}"
    multiplier = session.settings.get(f'color_{session.exploration_color}_multiplier', bonus['rare_multiplier'] * 100) / 100
    if multiplier > 1:
        description += '\n✨ この探索ではレア以上の宝物が出やすくなります。'
    description += cooperation_text(session)
    return discord.Embed(title='🗺️ 宝探し', description=description, color=color)


def map_start_embed(session):
    info = MAPS[session.map_tier]
    prefix = {'normal': '', 'copper': '銅の', 'silver': '銀の', 'gold': '金の'}[session.map_tier]
    name = f"{prefix}{session.difficulty_name}の宝の地図"
    map_bonus = session.settings.get(f'map_{session.map_tier}_bonus', info['bonus'])
    return discord.Embed(
        title=f"✨ {name}を手に入れた！",
        description=(f"{session.difficulty_name}宝探し\n\n💰 必要LIA：**{session.price:,} LIA**\n"
                     f"🎯 成功率：**{session.rate}%**\n"
                     f"地図の効果：+{map_bonus}ポイント（上限100%）\n"
                     "この宝探しの全探索判定に適用されます。"
                     f"\n🔎 最大探索：{session.max_exploration}回" + cooperation_text(session)),
        color=info['color'],
    )


def treasure_panel(settings):
    """難易度ごとの価格・成功率・探索回数を載せたEmbedを作る。"""
    embed = discord.Embed(
        title="🗺️ 宝探し",
        color=discord.Color.gold(),
        description="宝の地図を手に入れて、危険な場所を探索しよう！\n\n"
        "難易度が高いほど、必要なLIAも大きくなります。\n\n"
        "✨ 探索に成功するたびに宝物を1個発見！\n"
        "💥 失敗すると発見した宝物はすべて失われます。\n"
        "🏠 引き返せば、宝物の合計価値を確保できます。",
    )
    if settings.get('coop_enabled', 1):
        embed.description += '\n🤝 同じVCに仲間がいると探索回数・レア率がアップ！協力イベントのチャンスも。'
    for key, difficulty in DIFFICULTIES.items():
        embed.add_field(
            name=f"{difficulty['emoji']} {difficulty['name']}宝探し",
            value=f"必要LIA：{settings[f'{key}_price']:,}\n"
            f"成功率：{settings[f'{key}_rate']}%\n"
            f"最大探索：{settings[f'{key}_max']}回",
            inline=False,
        )
    embed.set_footer(text="※現在はLIAシステムとは未接続です")
    return embed


def _append_unlock_notification(text, session):
    """条件到達通知があれば結果の成否に関係なく追記する。消費は送信成功後に行う。"""
    if session.unlocked_difficulty:
        unlocked = DIFFICULTIES[session.unlocked_difficulty]
        text += (
            f"\n\n🔓 **難易度解放！**\n"
            f"{unlocked['emoji']} **{unlocked['name']}宝探し** が解放されました！"
        )
    return text


def exploration_text(session):
    """探索の進行状態や終了結果に応じたメッセージを作る。"""
    if session.result == "failure":
        text = (
            f"💥 **探索失敗！**\n\n{session.difficulty_name}宝探しで失敗しました。\n"
            "発見した宝物をすべて失いました。\n\n"
            f"🔎 探索回数：**{session.exploration_count}/{session.max_exploration}**\n"
            f"🎒 失った宝物：**{len(session.found_treasures)}個**\n"
            f"💰 失った宝物の合計価値：**{sum(t.price for t in session.found_treasures):,} LIA**\n"
            "💰 最終報酬：**0 LIA**"
        )
        return _append_unlock_notification(text, session)
    title = {
        "retreat": "🏠 **無事に引き返しました！**",
        "max_success": "🎉 **最大探索回数到達！**",
    }.get(session.result, "✨ **宝物を発見！**")
    discovery = ""
    if session.found_treasures and session.result in (None, "max_success"):
        treasure = session.found_treasures[-1]
        discovery = f"{treasure_name(treasure.name)}【{RARITIES[treasure.rarity]}】\n💰 価値：**{treasure.price:,} LIA**\n\n"
    text = (
        f"{title}\n\n{session.difficulty_name}宝探し\n"
        f"{discovery}"
        f"🔎 探索回数：**{session.exploration_count}/{session.max_exploration}**\n"
        f"🎒 発見した宝物：**{len(session.found_treasures)}個**\n"
        f"💰 {'最終報酬（宝物合計）' if session.result else '現在の合計価値'}：**{session.reward:,} LIA**"
    )
    # 難易度解放システム：成功・撤退・最大到達にも条件達成通知を追加する。
    text = _append_unlock_notification(text, session)
    if session.result is None:
        text += "\n\n⚔️ **さらに奥へ進みますか？**\n失敗すると発見した宝物をすべて失います。"
    return text


def treasure_name(name):
    return discord.utils.escape_mentions(discord.utils.escape_markdown(name))


def treasure_pages(found_treasures, lost=False):
    """一覧を行単位で分割する。絵文字もUTF-16単位で数え、2000文字に余裕を残す。"""
    heading = "🎒 **失った宝物一覧**" if lost else "🎒 **発見した宝物一覧**"
    lines = [
        f"探索{item.exploration_number}回目：{treasure_name(item.name)}【{RARITIES[item.rarity]}】 — {item.price:,} LIA\n"
        for item in found_treasures
    ] or ["宝物はありません。\n"]
    pages, page = [], heading + "\n\n"
    for line in lines:
        if len((page + line).encode("utf-16-le")) // 2 > 1800:
            pages.append(page)
            page = heading + "\n\n"
        page += line
    pages.append(page)
    return tuple(f"{text}\n{i}/{len(pages)}ページ" for i, text in enumerate(pages, 1))


def settings_text(settings):
    """現在の運営状態と難易度別設定を表示用の文章にする。"""
    text = (
        f"⚙️ **宝探し現在設定**\n\n運営状態：{'🟢 ON' if settings['operation'] else '🔴 OFF'}\n"
        f"テストモード：{TEST_MODES[settings['test_mode']]}\n\n"
    )
    for key, difficulty in DIFFICULTIES.items():
        text += (
            f"{difficulty['emoji']} **{difficulty['name']}**\n"
            f"💰 価格：{settings[f'{key}_price']:,} LIA\n"
            f"🎯 成功率：{settings[f'{key}_rate']}%\n"
            f"🔎 最大探索：{settings[f'{key}_max']}回\n\n"
        )
    # 難易度解放システム：管理者向け設定表示にも現在の条件を載せる。
    text += (
        "🔓 **難易度解放条件**\n"
        f"🔵 中級：初級を {settings['intermediate_unlock']}回 探索\n"
        f"🔴 上級：中級を {settings['advanced_unlock']}回 探索\n\n"
    )
    return text + "⚠️ 現在はLIAシステムとは未接続です。"


def statistics_text(summary):
    """通常プレイの集計結果を表示用の文章にする。"""
    text = f"📊 **宝探し統計**\n\n総プレイ数：**{summary['total']:,}回**\n\n"
    for difficulty in DIFFICULTIES.values():
        text += f"{difficulty['emoji']} {difficulty['name']}：{summary['difficulties'].get(difficulty['name'], 0):,}回\n"
    return (
        text + f"\n仮想消費LIA：**{summary['consumed']:,} LIA**\n"
        f"仮想報酬LIA：**{summary['payout']:,} LIA**\n最大仮想報酬：**{summary['max_payout']:,} LIA**\n\n"
        "※テストデータは除外。実際のLIA残高とは接続していません。"
    )


def history_entries(rows):
    """宝探し履歴を、送信時に分割できる文章の一覧にする。"""
    entries = ["📜 **宝探し最新10件**\n\n"]
    for row in rows:
        entries.append(
            f"**{discord.utils.escape_markdown(row['user_name'])}**{' 🧪' if row['is_test'] else ''}\n"
            f"{row['difficulty']} / 開始：{row['start_price']:,} LIA\n"
            f"成功：{row['success_count']}回 / 結果：{RESULT_NAMES.get(row['result'], row['result'])}\n"
            f"報酬：{row['final_reward']:,} LIA\n{row['created_at']}\n\n"
        )
    return entries if rows else entries + ["まだ履歴はありません。"]


def log_entries(rows):
    """管理者操作ログを、送信時に分割できる文章の一覧にする。"""
    entries = ["🔐 **管理者変更ログ 最新10件**\n\n"]
    for row in rows:
        entries.append(
            f"👤 {discord.utils.escape_markdown(row['admin_name'])}\n🔧 {row['action']}\n"
            f"📝 {row['detail']}\n🕐 {row['created_at']}\n\n"
        )
    return entries if rows else entries + ["まだログはありません。"]
