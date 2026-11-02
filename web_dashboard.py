"""AWSバッチの永続状態を表示する。物理エンジンは読み込まない。"""
import streamlit as st
import web_jobs as jobs

LABELS = {'queued': '待機中', 'running': '計算中', 'stopping': '停止処理中',
          'paused': '一時停止', 'completed': '完了', 'failed': 'エラー', 'interrupted': '中断'}


@st.fragment(run_every='3s')
def render():
    st.divider()
    st.subheader('AWSバッチの実行状況')
    online = jobs.worker_online()
    if not online:
        st.warning('計算ワーカーが動作していません。Ubuntuで barsim-worker サービスを起動してください。')
    entries = jobs.list_jobs()
    if not entries:
        st.caption('AWSバッチの実行履歴はまだありません。')
        return
    by_id = {job['id']: job for job in entries}
    chosen = st.selectbox('実行履歴（最新100件）', list(by_id),
                          format_func=lambda key: f"{by_id[key]['created']} / {LABELS[by_id[key]['status']]} / {key[:8]}",
                          key='aws_job_selected')
    job = by_id[chosen]
    st.write(f"状態：{LABELS[job['status']]}")
    st.caption('開始日時はUTCです。ブラウザを閉じても計算は継続します。')
    progress = jobs.read_progress(chosen)
    if progress:
        done, total = progress.get('done', 0), progress.get('total', 0)
        st.progress(min(1.0, done / total) if total else 0.0,
                    text=f'保存済み {done:,} / {total:,} タスク')
        if progress.get('eta_seconds') is not None:
            st.caption(f"残り時間の目安：約{progress['eta_seconds'] / 60:.1f}分")
    col1, col2 = st.columns(2)
    if col1.button('停止して保存', disabled=job['status'] not in ('queued', 'running'), key='aws_stop'):
        jobs.request_stop(chosen)
        st.rerun(scope='fragment')
    if col2.button('保存済み分から再開', disabled=not online or job['status'] not in ('paused', 'failed', 'interrupted'), key='aws_resume'):
        jobs.request_resume(chosen)
        st.rerun(scope='fragment')
    if job['message']:
        st.caption(job['message'])
    st.code(jobs.log_tail(chosen) or 'ログはまだありません。', language='text')
    folder = jobs.job_dir(chosen)
    st.download_button('計算条件JSONを保存', data=(folder / 'config.json').read_bytes(),
                       file_name=f'{chosen[:8]}_config.json', mime='application/json', key='aws_config_download')
    csv = folder / 'results' / 'simulation_results_aws.csv'
    if csv.exists():
        st.caption('CSVは完了・停止時に更新します。途中停止時は未完了の条件を含みます。')
        # 巨大CSVを自動更新のたびにメモリへ読み込まない。
        if csv.stat().st_size <= 100 * 1024**2:
            stamp = csv.stat().st_mtime_ns
            if st.button('CSVダウンロードを準備', key='aws_prepare_csv'):
                st.session_state['aws_download'] = (chosen, stamp, csv.read_bytes())
            prepared = st.session_state.get('aws_download')
            if prepared and prepared[:2] == (chosen, stamp):
                st.download_button('結果CSVをダウンロード', data=prepared[2],
                                   file_name=f'{chosen[:8]}_results.csv', mime='text/csv', key='aws_csv_download')
        else:
            st.info('CSVが100MiBを超えています。SSH/SCPで取得してください。')
    st.caption(f'サーバー上の保存先：{folder}')
