# Bambu P1S → ntfy（Windows / クラウド不要）

Bambu Lab P1S の**ローカルMQTT**をWindows上のPythonで監視し、印刷の状態変化を [ntfy](https://ntfy.sh/) でスマホに通知するツール。

- Bambuアカウント登録不要 / Bambu Cloud不要 / Docker不要
- 印刷開始、再開、一時停止、完了、失敗を通知
- P1Sへの接続を自動再試行。定期的に読み取り用 `pushall` を送信
- 状態をローカルファイルに保存して再起動時の重複通知を抑制
- Windowsタスクスケジューラでログオン時に常駐
- **プリンターのMQTT以外への操作（停止・移動・印刷開始など）は実行しません**

## 構成

`P1S --(Wi-Fi / LAN MQTT TLS:8883)--> Windows Python --(HTTPS)--> ntfy --push--> スマホ`

P1S側はインターネット接続不要。ntfy.shを使う場合はWindows PCからインターネットへアクセスできる必要があります。

## 1. BambuアカウントなしでWi-Fi設定（ステルスSSIDにも挑戦可能）

P1Sは2.4 GHzのWi-Fiを使用します。microSDカード直下に**平文テキスト**の `user_wifi.cfg` を作成します（拡張子 `.txt` が付かないように）。

```text
ssid:Your2point4GHzNetworkName
password:YourWiFiPassword
```

- SSID名・パスワードは実際の値に置換し、UTF-8のプレーンテキストで保存。
- 本体電源OFF → microSD挿入 → 電源ON → 本体のネットワーク画面で接続IPを確認。
- 既存Wi-Fi接続が残っている場合は一度「忘れる」操作が必要なことがあります。
- **ステルスSSID**はSDカード設定を利用できますが、ファームウェア・APとの組み合わせで接続不可の事例があります。接続できなければ一時的にSSIDブロードキャストを有効にして接続後に再び非公開へ戻す方法を検討してください（再接続成功は保証されません）。AP分離・ゲストネットワークにも注意。
- 接続確認後に `user_wifi.cfg` を削除してください（Wi-Fiパスワードが平文で残ります）。このファイルをGitに追加しないこと。

参考：[Bambu Wikiへのリンクがあるフォーラム](https://forum.bambulab.com/t/option-to-setup-wifi-connection-from-sd-card-file/157688) / [ステルスSSIDの報告](https://forum.bambulab.com/t/will-hidden-wifi-be-added/29603)

本体の設定で **LAN Only ModeをON**、対応ファームウェアでは **Developer ModeをON** にします。画面に表示される **IPアドレス、シリアル番号、LAN Access Code** を控えてください（GitHubや他人に共有しないでください）。Developer Modeではローカルポートが開くため、P1SとPCが信頼できるLAN上にあることが前提です。

> Bambu Cloud非使用の設定と、Wi-FiのステルスSSIDは別の話です。ステルスSSIDはそれ自体で強いセキュリティを保証しません。

## 2. Windowsセットアップ

**前提:** Windows 10/11、Python 3.10以降（`py -3` が使えること）、P1SとPC間でTCP 8883が通ること。

PowerShellで以下を実行：

```powershell
git clone https://github.com/bleach31/bambu-ntfy-win.git
cd bambu-ntfy-win
.\scripts\install.ps1
notepad config.json
```

PowerShell実行ポリシーで拒否された場合、当該PowerShellセッション限定で `Set-ExecutionPolicy -Scope Process Bypass` を使用できます。システム全体の設定を変更する必要はありません。

`config.json` は `config.example.json` のコピーとして作られます。編集する項目:

| 設定 | 値 |
| --- | --- |
| `printer.host` | P1SのLAN IP（例: 192.168.1.50） |
| `printer.serial` | P1Sのシリアル番号 |
| `printer.access_code` | 本体のLAN Access Code |
| `ntfy.server` | `https://ntfy.sh`、または自分のntfy HTTPSサーバー |
| `ntfy.topic` | 推測困難な長いランダムトピック名 |
| `ntfy.token` | 認証つきntfyの場合のみBearerトークン。通常は空欄 |
| `options.notify_initial_state` | `false`：起動直後の状態は通知せず、以降の変化だけ通知 |
| `options.include_job_name` | `true`：MQTTにファイル名があれば通知本文に含める |
| `options.refresh_seconds` | 状態更新のための `pushall` 周期（30～3600秒） |

`config.json` は **.gitignore登録済み**です。パスワードやトークンをコミットしないでください。

## 3. ntfyアプリ設定とテスト

スマホにntfyアプリを導入し、`ntfy.topic` と同じ名前のトピックを購読します。ntfy.shの匿名トピックは認証保護されません。推測しにくいトピック名を使い、機密情報を通知しないでください。必要なら認証付きセルフホストサーバーを使用します。

まずPC→ntfyの通信だけテスト：

```powershell
.\scripts\start.ps1 --test-notification
```

通知が届けばntfy側はOKです。その後P1SのMQTT接続を確認：

```powershell
Test-NetConnection 192.168.1.50 -Port 8883
.\scripts\start.ps1
```

IPは実際の `printer.host` に置換してください。ログは `.runtime\bambu-ntfy.log` に保存されます。終了するにはCtrl+Cを押します。

## 4. Windowsログオン時に自動起動

手動で一度通信を確認してから実行：

```powershell
.\scripts\register-task.ps1
Start-ScheduledTask -TaskName BambuP1S-Ntfy
```

- タスクは**現在のユーザーのログオン時**に起動。PCが起動していてもユーザー未ログオンなら起動しません。
- バックグラウンドは `pythonw.exe` を使用しコンソール非表示。動作確認はログを見ること。
- 二重起動すると通知が重複するため、手動の `start.ps1` 実行を終了してからタスクを起動してください。
- 削除: `.\scripts\remove-task.ps1`

## 5. 動作の詳細と制限

P1SのMQTT: TLS TCP/8883、ユーザー名 `bblp`、パスワード=LAN Access Code。購読 `device/<SERIAL>/report`、読取要求 `device/<SERIAL>/request` の `pushing.pushall`。 `print.gcode_state`（`RUNNING`、`PAUSE`、`FINISH`、`FAILED`など）を判定します。

印刷中にPCを立ち上げた場合、`notify_initial_state=false` なら最初の `RUNNING` は通知しませんが、その後の `FINISH` は通知します。印刷名は一部のファームウェアでは報告されないことがあります。ステータス報告には差分配信があるため、`gcode_state` が欠けるメッセージでは状態を変えません。

過去に観測した状態は `.runtime\state.json` に保存します。PC停止中の印刷開始・完了を後から正確に復元することはできません。ntfy通信失敗時はログに記録されますが、永続的な再送キューはありません。印刷安全監視の代わりにはしないでください。

P1SのTLS証明書は既定では検証できないため、この実装は**暗号化のみ使用しサーバー証明書を検証しません**。信頼できるローカルネットワークだけで利用し、インターネットへMQTTポートを公開しないでください。ntfyへのHTTPS通信は通常の証明書検証を行います。

トラブル時の切り分け:

1. Wi-Fiの2.4 GHz設定、SSID、DHCPアドレス取得を確認。
2. `Test-NetConnection ... -Port 8883` が失敗 → LAN Only/Developer Mode、AP隔離、VLAN/WindowsからP1Sへの到達性を確認。
3. TCPは通るがMQTT接続拒否 → Serial/Access Code・Developer Modeを確認。
4. MQTT接続するが通知が来ない → 本体で状態を変化させる、ログに `Printer state:` があるか確認。
5. ntfyテスト自体が失敗 → WindowsのDNS・HTTPS・プロキシ・ntfyサーバーと購読トピックを確認。

## テスト

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 参照

- [Bambu公式: サードパーティ統合とDeveloper Mode](https://blog.bambulab.com/updates-and-third-party-integration-with-bambu-connect/)
- [OpenBambuAPI MQTT](https://github.com/Doridian/OpenBambuAPI/blob/main/mqtt.md)
- [P1S LAN Only / Developer設定例](https://github.com/mklod/bambu-bridge/blob/main/docs/lan-only-setup.md)
- [ntfy Publishing](https://docs.ntfy.sh/publish/)
