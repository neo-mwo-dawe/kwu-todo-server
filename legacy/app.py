"""
app.py
광운대 KLAS 연동 TODO 대시보드 Flask 서버
"""

from flask import Flask, render_template_string, request, jsonify, session, redirect, url_for
import os
import json
from datetime import datetime
from klas_crawler import KLASClient, TodayTask

app = Flask(__name__)
app.secret_key = os.urandom(24)

# 세션별 KLAS 클라이언트 저장 (실제 서비스에선 Redis 등 사용)
_klas_clients = {}


# ──────────────────────────────────────────────
# HTML 템플릿 - 로그인 페이지
# ──────────────────────────────────────────────

LOGIN_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>광운대 학습 도우미 - 로그인</title>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;700&display=swap" rel="stylesheet">
<style>
  :root {
    --kw-blue: #003087;
    --kw-blue-light: #0044bb;
    --kw-gold: #c8a217;
    --bg: #f0f3f8;
    --card: #ffffff;
    --text: #1a1a2e;
    --sub: #5a6380;
    --border: #dde3f0;
    --error: #e53e3e;
    --success: #2f855a;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: 'Noto Sans KR', sans-serif;
    background: var(--bg);
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    background-image:
      radial-gradient(ellipse at 20% 50%, rgba(0,48,135,0.08) 0%, transparent 60%),
      radial-gradient(ellipse at 80% 20%, rgba(200,162,23,0.06) 0%, transparent 50%);
  }

  .container {
    width: 100%;
    max-width: 420px;
    padding: 24px;
  }

  .logo-area {
    text-align: center;
    margin-bottom: 32px;
  }

  .logo-badge {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    background: var(--kw-blue);
    color: white;
    padding: 10px 20px;
    border-radius: 50px;
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.5px;
    margin-bottom: 16px;
  }

  .logo-badge .dot {
    width: 8px;
    height: 8px;
    background: var(--kw-gold);
    border-radius: 50%;
  }

  h1 {
    font-size: 26px;
    font-weight: 700;
    color: var(--text);
    margin-bottom: 6px;
  }

  .subtitle {
    font-size: 14px;
    color: var(--sub);
    font-weight: 300;
  }

  .card {
    background: var(--card);
    border-radius: 20px;
    padding: 36px 32px;
    box-shadow:
      0 4px 6px rgba(0,0,0,0.04),
      0 20px 40px rgba(0,48,135,0.08);
    border: 1px solid var(--border);
  }

  .form-group {
    margin-bottom: 20px;
  }

  label {
    display: block;
    font-size: 12px;
    font-weight: 600;
    color: var(--sub);
    letter-spacing: 0.8px;
    text-transform: uppercase;
    margin-bottom: 8px;
  }

  input {
    width: 100%;
    padding: 14px 16px;
    border: 1.5px solid var(--border);
    border-radius: 12px;
    font-size: 15px;
    font-family: 'Noto Sans KR', sans-serif;
    color: var(--text);
    background: #fafbfd;
    transition: all 0.2s;
    outline: none;
  }

  input:focus {
    border-color: var(--kw-blue);
    background: white;
    box-shadow: 0 0 0 3px rgba(0,48,135,0.08);
  }

  input::placeholder { color: #b0b8cc; }

  .btn-login {
    width: 100%;
    padding: 15px;
    background: var(--kw-blue);
    color: white;
    border: none;
    border-radius: 12px;
    font-size: 15px;
    font-weight: 600;
    font-family: 'Noto Sans KR', sans-serif;
    cursor: pointer;
    transition: all 0.2s;
    margin-top: 8px;
    position: relative;
    overflow: hidden;
  }

  .btn-login:hover {
    background: var(--kw-blue-light);
    transform: translateY(-1px);
    box-shadow: 0 6px 20px rgba(0,48,135,0.3);
  }

  .btn-login:active { transform: translateY(0); }

  .btn-login.loading {
    pointer-events: none;
    opacity: 0.8;
  }

  .btn-login .spinner {
    display: none;
    width: 18px;
    height: 18px;
    border: 2px solid rgba(255,255,255,0.3);
    border-top-color: white;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    margin: 0 auto;
  }

  .btn-login.loading .btn-text { display: none; }
  .btn-login.loading .spinner { display: block; }

  @keyframes spin { to { transform: rotate(360deg); } }

  .error-msg {
    display: none;
    background: #fff5f5;
    border: 1px solid #feb2b2;
    border-radius: 10px;
    padding: 12px 16px;
    font-size: 13px;
    color: var(--error);
    margin-top: 16px;
    text-align: center;
  }

  .error-msg.show { display: block; }

  .notice {
    margin-top: 20px;
    padding: 12px 16px;
    background: #f0f4ff;
    border-radius: 10px;
    font-size: 12px;
    color: var(--sub);
    line-height: 1.6;
  }

  .notice strong { color: var(--kw-blue); }

  .divider {
    height: 1px;
    background: var(--border);
    margin: 24px 0;
  }

  .klas-link {
    text-align: center;
    font-size: 12px;
    color: var(--sub);
  }

  .klas-link a {
    color: var(--kw-blue);
    text-decoration: none;
    font-weight: 500;
  }

  .klas-link a:hover { text-decoration: underline; }

  .features {
    display: flex;
    gap: 8px;
    margin-top: 24px;
    justify-content: center;
  }

  .feature-tag {
    font-size: 11px;
    padding: 4px 10px;
    border-radius: 20px;
    background: var(--bg);
    color: var(--sub);
    border: 1px solid var(--border);
  }
</style>
</head>
<body>
<div class="container">
  <div class="logo-area">
    <div class="logo-badge">
      <span class="dot"></span>
      광운대학교 학습 도우미
    </div>
    <h1>오늘 할 일 확인</h1>
    <p class="subtitle">KLAS 계정으로 로그인하면 자동으로 수집합니다</p>
  </div>

  <div class="card">
    <div class="form-group">
      <label>학번</label>
      <input type="text" id="studentId" placeholder="학번을 입력하세요" maxlength="20" autocomplete="username">
    </div>
    <div class="form-group">
      <label>비밀번호</label>
      <input type="password" id="password" placeholder="비밀번호를 입력하세요" autocomplete="current-password">
    </div>

    <button class="btn-login" id="loginBtn" onclick="doLogin()">
      <span class="btn-text">로그인 및 할 일 불러오기</span>
      <div class="spinner"></div>
    </button>

    <div class="error-msg" id="errorMsg"></div>

    <div class="divider"></div>

    <div class="notice">
      <strong>🔒 보안 안내</strong><br>
      입력하신 정보는 KLAS 인증에만 사용되며 저장되지 않습니다.
      광운대 공식 KLAS(<a href="https://klas.kw.ac.kr" target="_blank" style="color:var(--kw-blue)">klas.kw.ac.kr</a>)와 동일한 계정을 사용합니다.
    </div>

    <div class="klas-link">
      <a href="https://klas.kw.ac.kr/usr/cmn/login/LoginForm.do" target="_blank">KLAS 비밀번호 찾기 →</a>
    </div>
  </div>

  <div class="features">
    <span class="feature-tag">📚 과제 마감</span>
    <span class="feature-tag">📅 학사일정</span>
    <span class="feature-tag">✅ 퀴즈/시험</span>
  </div>
</div>

<script>
document.addEventListener('keydown', function(e) {
  if (e.key === 'Enter') doLogin();
});

async function doLogin() {
  const studentId = document.getElementById('studentId').value.trim();
  const password = document.getElementById('password').value;
  const btn = document.getElementById('loginBtn');
  const errorDiv = document.getElementById('errorMsg');

  if (!studentId || !password) {
    showError('학번과 비밀번호를 모두 입력해주세요.');
    return;
  }

  btn.classList.add('loading');
  errorDiv.classList.remove('show');

  try {
    const res = await fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ student_id: studentId, password: password })
    });
    const data = await res.json();

    if (data.success) {
      window.location.href = '/dashboard';
    } else {
      showError(data.message || '로그인에 실패했습니다.');
    }
  } catch (e) {
    showError('서버 연결에 실패했습니다. 잠시 후 다시 시도해주세요.');
  } finally {
    btn.classList.remove('loading');
  }
}

function showError(msg) {
  const el = document.getElementById('errorMsg');
  el.textContent = msg;
  el.classList.add('show');
}
</script>
</body>
</html>"""


# ──────────────────────────────────────────────
# HTML 템플릿 - 대시보드
# ──────────────────────────────────────────────

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>오늘 할 일 - 광운대 학습 도우미</title>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;700;900&display=swap" rel="stylesheet">
<style>
  :root {
    --kw-blue: #003087;
    --kw-blue-light: #0044bb;
    --kw-gold: #c8a217;
    --bg: #f0f3f8;
    --card: #ffffff;
    --text: #1a1a2e;
    --sub: #5a6380;
    --border: #dde3f0;
    --p1: #fff1f1;
    --p1-border: #fc8181;
    --p1-text: #c53030;
    --p2: #fffaf0;
    --p2-border: #f6ad55;
    --p2-text: #c05621;
    --p3: #fffff0;
    --p3-border: #f6e05e;
    --p3-text: #975a16;
    --p4: #f0fff4;
    --p4-border: #68d391;
    --p4-text: #276749;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: 'Noto Sans KR', sans-serif;
    background: var(--bg);
    min-height: 100vh;
    background-image:
      radial-gradient(ellipse at 10% 0%, rgba(0,48,135,0.06) 0%, transparent 50%),
      radial-gradient(ellipse at 90% 100%, rgba(200,162,23,0.04) 0%, transparent 50%);
  }

  /* ── 헤더 ── */
  .header {
    background: var(--kw-blue);
    color: white;
    padding: 0 32px;
    height: 64px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    position: sticky;
    top: 0;
    z-index: 100;
    box-shadow: 0 2px 12px rgba(0,48,135,0.3);
  }

  .header-left {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .header-logo {
    width: 32px;
    height: 32px;
    background: var(--kw-gold);
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 18px;
  }

  .header-title {
    font-size: 16px;
    font-weight: 700;
    letter-spacing: -0.3px;
  }

  .header-right {
    display: flex;
    align-items: center;
    gap: 16px;
  }

  .student-badge {
    font-size: 13px;
    opacity: 0.9;
    font-weight: 300;
  }

  .student-badge strong {
    font-weight: 700;
  }

  .btn-logout {
    background: rgba(255,255,255,0.15);
    color: white;
    border: 1px solid rgba(255,255,255,0.3);
    padding: 6px 14px;
    border-radius: 8px;
    font-size: 12px;
    cursor: pointer;
    font-family: 'Noto Sans KR', sans-serif;
    transition: all 0.2s;
  }

  .btn-logout:hover { background: rgba(255,255,255,0.25); }

  /* ── 메인 콘텐츠 ── */
  .main {
    max-width: 900px;
    margin: 0 auto;
    padding: 32px 24px;
  }

  /* ── 날짜/요약 배너 ── */
  .today-banner {
    background: white;
    border-radius: 16px;
    padding: 24px 28px;
    margin-bottom: 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    border: 1px solid var(--border);
    box-shadow: 0 2px 8px rgba(0,48,135,0.05);
  }

  .today-date {
    font-size: 28px;
    font-weight: 900;
    color: var(--text);
    letter-spacing: -1px;
  }

  .today-sub {
    font-size: 13px;
    color: var(--sub);
    margin-top: 4px;
  }

  .today-stats {
    display: flex;
    gap: 16px;
  }

  .stat-item {
    text-align: center;
    padding: 12px 20px;
    border-radius: 12px;
    min-width: 80px;
  }

  .stat-item.urgent { background: var(--p1); }
  .stat-item.high   { background: var(--p2); }
  .stat-item.normal { background: var(--p4); }

  .stat-num {
    font-size: 24px;
    font-weight: 900;
  }
  .stat-item.urgent .stat-num { color: var(--p1-text); }
  .stat-item.high   .stat-num { color: var(--p2-text); }
  .stat-item.normal .stat-num { color: var(--p4-text); }

  .stat-label {
    font-size: 11px;
    color: var(--sub);
    margin-top: 2px;
  }

  /* ── 필터 탭 ── */
  .filter-tabs {
    display: flex;
    gap: 8px;
    margin-bottom: 20px;
    flex-wrap: wrap;
  }

  .tab {
    padding: 8px 16px;
    border-radius: 50px;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    border: 1.5px solid var(--border);
    background: white;
    color: var(--sub);
    transition: all 0.2s;
    font-family: 'Noto Sans KR', sans-serif;
  }

  .tab:hover { border-color: var(--kw-blue); color: var(--kw-blue); }

  .tab.active {
    background: var(--kw-blue);
    border-color: var(--kw-blue);
    color: white;
  }

  /* ── 할 일 카드 ── */
  .task-section {
    margin-bottom: 24px;
  }

  .section-label {
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.8px;
    text-transform: uppercase;
    color: var(--sub);
    margin-bottom: 10px;
    padding-left: 4px;
  }

  .task-card {
    background: white;
    border-radius: 14px;
    padding: 18px 20px;
    margin-bottom: 10px;
    border: 1.5px solid var(--border);
    display: flex;
    align-items: flex-start;
    gap: 14px;
    transition: all 0.2s;
    cursor: pointer;
    text-decoration: none;
    color: inherit;
  }

  .task-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 24px rgba(0,48,135,0.1);
    border-color: var(--kw-blue);
  }

  .task-card.p1 { border-left: 4px solid var(--p1-border); }
  .task-card.p2 { border-left: 4px solid var(--p2-border); }
  .task-card.p3 { border-left: 4px solid var(--p3-border); }
  .task-card.p4 { border-left: 4px solid var(--p4-border); }

  .task-icon {
    width: 40px;
    height: 40px;
    border-radius: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 18px;
    flex-shrink: 0;
  }

  .task-icon.과제 { background: #ebf4ff; }
  .task-icon.퀴즈 { background: #fef3c7; }
  .task-icon.시험 { background: #fee2e2; }
  .task-icon.공지 { background: #e0e7ff; }
  .task-icon.학사일정 { background: #f0fdf4; }
  .task-icon.토론 { background: #fdf4ff; }

  .task-content { flex: 1; min-width: 0; }

  .task-meta {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 4px;
    flex-wrap: wrap;
  }

  .task-course {
    font-size: 11px;
    font-weight: 600;
    color: var(--kw-blue);
    background: rgba(0,48,135,0.06);
    padding: 2px 8px;
    border-radius: 4px;
  }

  .task-type-badge {
    font-size: 11px;
    color: var(--sub);
    padding: 2px 8px;
    border-radius: 4px;
    border: 1px solid var(--border);
  }

  .task-title {
    font-size: 15px;
    font-weight: 600;
    color: var(--text);
    margin-bottom: 6px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .task-due {
    font-size: 12px;
    color: var(--sub);
    display: flex;
    align-items: center;
    gap: 4px;
  }

  .task-due.urgent { color: var(--p1-text); font-weight: 600; }
  .task-due.high   { color: var(--p2-text); font-weight: 500; }

  .task-arrow {
    color: var(--border);
    font-size: 18px;
    flex-shrink: 0;
    align-self: center;
  }

  /* ── 빈 상태 ── */
  .empty-state {
    text-align: center;
    padding: 60px 24px;
    color: var(--sub);
  }

  .empty-state .emoji { font-size: 48px; margin-bottom: 16px; }
  .empty-state h3 { font-size: 18px; font-weight: 700; color: var(--text); margin-bottom: 8px; }
  .empty-state p { font-size: 14px; }

  /* ── 로딩 ── */
  .loading-overlay {
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(0,48,135,0.85);
    z-index: 999;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    color: white;
  }

  .loading-overlay.show { display: flex; }

  .loading-spinner {
    width: 48px;
    height: 48px;
    border: 3px solid rgba(255,255,255,0.2);
    border-top-color: white;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    margin-bottom: 16px;
  }

  @keyframes spin { to { transform: rotate(360deg); } }

  .loading-text { font-size: 16px; font-weight: 500; }
  .loading-sub  { font-size: 13px; opacity: 0.7; margin-top: 6px; }

  /* ── 새로고침 버튼 ── */
  .refresh-btn {
    display: flex;
    align-items: center;
    gap: 8px;
    background: white;
    border: 1.5px solid var(--border);
    padding: 8px 16px;
    border-radius: 10px;
    font-size: 13px;
    color: var(--sub);
    cursor: pointer;
    font-family: 'Noto Sans KR', sans-serif;
    transition: all 0.2s;
  }

  .refresh-btn:hover { border-color: var(--kw-blue); color: var(--kw-blue); }

  .header-actions { display: flex; align-items: center; gap: 10px; }

  @media (max-width: 640px) {
    .today-banner { flex-direction: column; gap: 16px; align-items: flex-start; }
    .today-stats { width: 100%; justify-content: space-between; }
    .header { padding: 0 16px; }
    .main { padding: 20px 16px; }
    .student-badge { display: none; }
  }
</style>
</head>
<body>

<div class="loading-overlay" id="loadingOverlay">
  <div class="loading-spinner"></div>
  <div class="loading-text">KLAS에서 데이터를 가져오는 중...</div>
  <div class="loading-sub">과제, 퀴즈, 학사일정을 확인합니다</div>
</div>

<header class="header">
  <div class="header-left">
    <div class="header-logo">📚</div>
    <div class="header-title">광운대 학습 도우미</div>
  </div>
  <div class="header-right">
    <span class="student-badge" id="studentBadge"></span>
    <div class="header-actions">
      <button class="refresh-btn" onclick="refreshTasks()">↻ 새로고침</button>
      <button class="btn-logout" onclick="logout()">로그아웃</button>
    </div>
  </div>
</header>

<main class="main">
  <div class="today-banner">
    <div>
      <div class="today-date" id="todayDate"></div>
      <div class="today-sub" id="semesterInfo"></div>
    </div>
    <div class="today-stats">
      <div class="stat-item urgent">
        <div class="stat-num" id="cnt1">-</div>
        <div class="stat-label">긴급</div>
      </div>
      <div class="stat-item high">
        <div class="stat-num" id="cnt2">-</div>
        <div class="stat-label">이번주</div>
      </div>
      <div class="stat-item normal">
        <div class="stat-num" id="cnt3">-</div>
        <div class="stat-label">여유</div>
      </div>
    </div>
  </div>

  <div class="filter-tabs">
    <button class="tab active" onclick="filterTasks('all', this)">전체</button>
    <button class="tab" onclick="filterTasks('과제', this)">📝 과제</button>
    <button class="tab" onclick="filterTasks('퀴즈', this)">❓ 퀴즈</button>
    <button class="tab" onclick="filterTasks('시험', this)">📋 시험</button>
    <button class="tab" onclick="filterTasks('학사일정', this)">📅 학사일정</button>
  </div>

  <div id="taskContainer">
    <div class="empty-state">
      <div class="emoji">⏳</div>
      <h3>불러오는 중...</h3>
    </div>
  </div>
</main>

<script>
let allTasks = [];

const TYPE_ICONS = {
  '과제': '📝', '퀴즈': '❓', '시험': '📋',
  '공지': '📢', '학사일정': '📅', '토론': '💬'
};

// 날짜 표시
const now = new Date();
const days = ['일', '월', '화', '수', '목', '금', '토'];
document.getElementById('todayDate').textContent =
  `${now.getMonth()+1}월 ${now.getDate()}일 (${days[now.getDay()]})`;

// 학생 정보 로드
async function loadStudentInfo() {
  try {
    const res = await fetch('/api/student-info');
    const data = await res.json();
    if (data.name) {
      document.getElementById('studentBadge').innerHTML =
        `<strong>${data.name}</strong> 님 (${data.student_id})`;
    }
    if (data.semester) {
      document.getElementById('semesterInfo').textContent = data.semester;
    }
  } catch(e) {}
}

// 할 일 로드
async function loadTasks() {
  document.getElementById('loadingOverlay').classList.add('show');
  try {
    const res = await fetch('/api/tasks');
    const data = await res.json();

    if (data.redirect) {
      window.location.href = data.redirect;
      return;
    }

    allTasks = data.tasks || [];
    renderTasks(allTasks);
    updateStats(allTasks);
  } catch(e) {
    document.getElementById('taskContainer').innerHTML = `
      <div class="empty-state">
        <div class="emoji">⚠️</div>
        <h3>데이터를 불러올 수 없습니다</h3>
        <p>KLAS 서버에 연결하지 못했습니다. 잠시 후 새로고침 해주세요.</p>
      </div>`;
  } finally {
    document.getElementById('loadingOverlay').classList.remove('show');
  }
}

function updateStats(tasks) {
  document.getElementById('cnt1').textContent = tasks.filter(t => t.priority === 1).length;
  document.getElementById('cnt2').textContent = tasks.filter(t => t.priority === 2).length;
  document.getElementById('cnt3').textContent = tasks.filter(t => t.priority === 3).length;
}

function filterTasks(type, btn) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  btn.classList.add('active');
  const filtered = type === 'all' ? allTasks : allTasks.filter(t => t.task_type === type);
  renderTasks(filtered);
}

function renderTasks(tasks) {
  const container = document.getElementById('taskContainer');

  if (!tasks.length) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="emoji">🎉</div>
        <h3>할 일이 없습니다!</h3>
        <p>마감 임박한 과제나 일정이 없어요. 여유롭게 보내세요!</p>
      </div>`;
    return;
  }

  // 우선순위 그룹별 렌더링
  const groups = {
    1: { label: '🔴 긴급 — 48시간 이내', tasks: [] },
    2: { label: '🟠 이번 주 마감', tasks: [] },
    3: { label: '🟢 여유', tasks: [] },
  };

  tasks.forEach(t => {
    const p = t.priority <= 1 ? 1 : t.priority <= 2 ? 2 : 3;
    if (groups[p]) groups[p].tasks.push(t);
  });

  let html = '';
  for (const [p, group] of Object.entries(groups)) {
    if (!group.tasks.length) continue;
    html += `<div class="task-section">
      <div class="section-label">${group.label}</div>`;

    group.tasks.forEach(task => {
      const icon = TYPE_ICONS[task.task_type] || '📌';
      const dueClass = p === '1' ? 'urgent' : p === '2' ? 'high' : '';
      const cardUrl = task.url || '#';
      html += `
        <a class="task-card p${p}" href="${cardUrl}" target="${task.url ? '_blank' : '_self'}">
          <div class="task-icon ${task.task_type}">${icon}</div>
          <div class="task-content">
            <div class="task-meta">
              <span class="task-course">${task.course_name}</span>
              <span class="task-type-badge">${task.task_type}</span>
            </div>
            <div class="task-title">${task.title}</div>
            <div class="task-due ${dueClass}">⏰ ${task.due_str || '마감일 미정'}</div>
          </div>
          ${task.url ? '<div class="task-arrow">›</div>' : ''}
        </a>`;
    });
    html += '</div>';
  }

  container.innerHTML = html;
}

async function refreshTasks() {
  await loadTasks();
}

async function logout() {
  await fetch('/api/logout', { method: 'POST' });
  window.location.href = '/';
}

// 초기 로드
loadStudentInfo();
loadTasks();
</script>
</body>
</html>"""


# ──────────────────────────────────────────────
# Flask 라우트
# ──────────────────────────────────────────────

@app.route("/")
def index():
    if session.get("logged_in"):
        return redirect(url_for("dashboard"))
    return render_template_string(LOGIN_HTML)


@app.route("/dashboard")
def dashboard():
    if not session.get("logged_in"):
        return redirect(url_for("index"))
    return render_template_string(DASHBOARD_HTML)


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json()
    student_id = (data.get("student_id") or "").strip()
    password   = data.get("password") or ""

    if not student_id or not password:
        return jsonify({"success": False, "message": "학번과 비밀번호를 입력해주세요."})

    client = KLASClient()
    result = client.login(student_id, password)

    if result["success"]:
        session["logged_in"] = True
        session["student_id"] = student_id
        _klas_clients[student_id] = client

        student = result["student"]
        session["student_name"] = student.name
        session["student_dept"] = student.department
        session["semester"] = student.semester

        return jsonify({
            "success": True,
            "message": "로그인 성공",
            "student": {
                "name": student.name,
                "student_id": student_id,
                "department": student.department,
                "semester": student.semester,
            }
        })
    else:
        return jsonify({"success": False, "message": result["message"]}), 401


@app.route("/api/student-info")
def api_student_info():
    if not session.get("logged_in"):
        return jsonify({"redirect": "/"})
    return jsonify({
        "name": session.get("student_name", ""),
        "student_id": session.get("student_id", ""),
        "department": session.get("student_dept", ""),
        "semester": session.get("semester", ""),
    })


@app.route("/api/tasks")
def api_tasks():
    if not session.get("logged_in"):
        return jsonify({"redirect": "/"})

    student_id = session.get("student_id")
    client = _klas_clients.get(student_id)

    if not client:
        return jsonify({"redirect": "/"})

    try:
        tasks = client.get_today_tasks()
        return jsonify({
            "tasks": [
                {
                    "title": t.title,
                    "course_name": t.course_name,
                    "task_type": t.task_type,
                    "due_str": t.due_str,
                    "priority": t.priority,
                    "priority_label": t.priority_label,
                    "url": t.url,
                    "days_left": t.days_left,
                }
                for t in tasks
            ]
        })
    except Exception as e:
        logger.error(f"[API] 할 일 수집 오류: {e}")
        return jsonify({"tasks": [], "error": str(e)})


@app.route("/api/logout", methods=["POST"])
def api_logout():
    student_id = session.get("student_id")
    if student_id and student_id in _klas_clients:
        try:
            _klas_clients[student_id].close()
        except:
            pass
        del _klas_clients[student_id]
    session.clear()
    return jsonify({"success": True})


if __name__ == "__main__":
    print("=" * 50)
    print("  광운대 학습 도우미 서버 시작")
    print("  http://localhost:5000 에서 접속하세요")
    print("=" * 50)
    app.run(debug=True, port=5000, host="0.0.0.0")
