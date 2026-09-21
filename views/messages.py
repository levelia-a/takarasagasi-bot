import discord

from consts.treasure import DIFFICULTIES, RESULT_NAMES, TEST_MODES


def treasure_panel(settings):
    """難易度ごとの価格・成功率・探索回数を載せたEmbedを作る。"""
    embed = discord.Embed(
        title="🗺️ 宝探し",
        color=discord.Color.gold(),
        description="宝の地図を手に入れて、危険な場所を探索しよう！\n\n"
        "難易度が高いほど、必要なLIAも大きくなります。\n\n"
        "✨ 探索に成功すると報酬が2倍！\n"
        "💥 失敗すると獲得報酬はすべて失われます。\n"
        "🏠 引き返せば、その時点の報酬を確保できます。",
    )
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
        text = f"💥 **探索失敗！**\n\n{session.difficulty_name}宝探しで失敗しました。\n報酬はすべて失われます。\n\n💰 最終報酬：**0 LIA**"
        return _append_unlock_notification(text, session)
    title = {
        "retreat": "🏠 **無事に引き返しました！**",
        "max_success": "🎉 **最大探索回数到達！**",
    }.get(session.result, "✨ **探索成功！**\n\n報酬が2倍になりました！")
    text = (
        f"{title}\n\n{session.difficulty_name}宝探し\n"
        f"🔎 探索回数：**{session.exploration_count}/{session.max_exploration}**\n"
        f"✨ 成功回数：**{session.success_count}回**\n"
        f"💰 {'獲得報酬' if session.result else '現在の報酬'}：**{session.reward:,} LIA**"
    )
    # 難易度解放システム：成功・撤退・最大到達にも条件達成通知を追加する。
    text = _append_unlock_notification(text, session)
    if session.result is None:
        text += "\n\n⚔️ **さらに奥へ進みますか？**\n失敗すると報酬はすべて失われます。"
    return text


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
