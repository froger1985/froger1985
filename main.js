const canvas = document.getElementById('gameCanvas');
const ctx = canvas.getContext('2d');

const CANVAS_W = 480;
const CANVAS_H = 560;
canvas.width = CANVAS_W;
canvas.height = CANVAS_H;

// HUD elements
const scoreEl = document.getElementById('score');
const levelEl = document.getElementById('level');
const livesEl = document.getElementById('lives');
const messageEl = document.getElementById('message');
const msgTitle = document.getElementById('msg-title');
const msgBody = document.getElementById('msg-body');
const msgBtn = document.getElementById('msg-btn');

// Game state
let score = 0;
let lives = 3;
let level = 1;
let gameState = 'idle'; // idle | playing | paused | gameover | win

// Paddle
const PADDLE_H = 10;
const PADDLE_Y = CANVAS_H - 40;
let paddle = {
  x: CANVAS_W / 2,
  w: 80,
  speed: 6,
};

// Ball
let ball = {
  x: 0, y: 0,
  vx: 0, vy: 0,
  r: 7,
};

// Bricks
const BRICK_ROWS = 5;
const BRICK_COLS = 9;
const BRICK_H = 22;
const BRICK_GAP = 5;
const BRICK_OFFSET_TOP = 60;
const BRICK_OFFSET_X = 16;

const BRICK_COLORS = [
  { fill: '#ff4d6d', shadow: '#ff4d6d88' },
  { fill: '#ff9f1c', shadow: '#ff9f1c88' },
  { fill: '#ffdd00', shadow: '#ffdd0088' },
  { fill: '#06d6a0', shadow: '#06d6a088' },
  { fill: '#00b4d8', shadow: '#00b4d888' },
];

let bricks = [];

function brickWidth() {
  return (CANVAS_W - BRICK_OFFSET_X * 2 - BRICK_GAP * (BRICK_COLS - 1)) / BRICK_COLS;
}

function initBricks() {
  bricks = [];
  const bw = brickWidth();
  for (let r = 0; r < BRICK_ROWS; r++) {
    for (let c = 0; c < BRICK_COLS; c++) {
      const hp = (BRICK_ROWS - r <= 2) ? 2 : 1;
      bricks.push({
        x: BRICK_OFFSET_X + c * (bw + BRICK_GAP),
        y: BRICK_OFFSET_TOP + r * (BRICK_H + BRICK_GAP),
        w: bw,
        h: BRICK_H,
        hp,
        maxHp: hp,
        color: BRICK_COLORS[r % BRICK_COLORS.length],
      });
    }
  }
}

function resetBall() {
  ball.x = paddle.x;
  ball.y = PADDLE_Y - ball.r - 1;
  const angle = (-Math.PI / 2) + (Math.random() - 0.5) * (Math.PI / 3);
  const speed = 4 + (level - 1) * 0.4;
  ball.vx = Math.cos(angle) * speed;
  ball.vy = Math.sin(angle) * speed;
}

function resetGame() {
  score = 0;
  lives = 3;
  level = 1;
  paddle.x = CANVAS_W / 2;
  paddle.w = 80;
  initBricks();
  resetBall();
  updateHUD();
}

function updateHUD() {
  scoreEl.textContent = score;
  levelEl.textContent = level;
  livesEl.textContent = lives;
}

function showMessage(title, body, btnText) {
  msgTitle.textContent = title;
  msgBody.textContent = body;
  msgBtn.textContent = btnText;
  messageEl.style.display = 'block';
}

function hideMessage() {
  messageEl.style.display = 'none';
}

// Input
const keys = {};
document.addEventListener('keydown', e => { keys[e.key] = true; });
document.addEventListener('keyup', e => { keys[e.key] = false; });

canvas.addEventListener('mousemove', e => {
  if (gameState !== 'playing') return;
  const rect = canvas.getBoundingClientRect();
  paddle.x = e.clientX - rect.left;
  clampPaddle();
});

canvas.addEventListener('touchmove', e => {
  if (gameState !== 'playing') return;
  e.preventDefault();
  const rect = canvas.getBoundingClientRect();
  paddle.x = e.touches[0].clientX - rect.left;
  clampPaddle();
}, { passive: false });

function clampPaddle() {
  paddle.x = Math.max(paddle.w / 2, Math.min(CANVAS_W - paddle.w / 2, paddle.x));
}

msgBtn.addEventListener('click', () => {
  if (gameState === 'gameover' || gameState === 'win') {
    resetGame();
  }
  hideMessage();
  gameState = 'playing';
});

// Collision helpers
function rectOverlap(ball, brick) {
  return (
    ball.x + ball.r > brick.x &&
    ball.x - ball.r < brick.x + brick.w &&
    ball.y + ball.r > brick.y &&
    ball.y - ball.r < brick.y + brick.h
  );
}

function resolveCollision(ball, brick) {
  const overlapLeft = (ball.x + ball.r) - brick.x;
  const overlapRight = (brick.x + brick.w) - (ball.x - ball.r);
  const overlapTop = (ball.y + ball.r) - brick.y;
  const overlapBottom = (brick.y + brick.h) - (ball.y - ball.r);

  const minOverlap = Math.min(overlapLeft, overlapRight, overlapTop, overlapBottom);

  if (minOverlap === overlapTop || minOverlap === overlapBottom) {
    ball.vy *= -1;
  } else {
    ball.vx *= -1;
  }
}

// Particle effects
let particles = [];

function spawnParticles(x, y, color) {
  for (let i = 0; i < 8; i++) {
    const angle = (Math.PI * 2 / 8) * i + Math.random() * 0.4;
    const speed = 1.5 + Math.random() * 2;
    particles.push({
      x, y,
      vx: Math.cos(angle) * speed,
      vy: Math.sin(angle) * speed,
      r: 2 + Math.random() * 2,
      life: 1,
      decay: 0.04 + Math.random() * 0.03,
      color: color.fill,
    });
  }
}

function updateParticles() {
  for (let i = particles.length - 1; i >= 0; i--) {
    const p = particles[i];
    p.x += p.vx;
    p.y += p.vy;
    p.life -= p.decay;
    if (p.life <= 0) particles.splice(i, 1);
  }
}

function drawParticles() {
  for (const p of particles) {
    ctx.globalAlpha = p.life;
    ctx.fillStyle = p.color;
    ctx.beginPath();
    ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.globalAlpha = 1;
}

// Update logic
function update() {
  if (gameState !== 'playing') return;

  // Keyboard paddle movement
  if (keys['ArrowLeft'] || keys['a'] || keys['A']) {
    paddle.x -= paddle.speed;
  }
  if (keys['ArrowRight'] || keys['d'] || keys['D']) {
    paddle.x += paddle.speed;
  }
  clampPaddle();

  // Move ball
  ball.x += ball.vx;
  ball.y += ball.vy;

  // Wall collisions
  if (ball.x - ball.r < 0) {
    ball.x = ball.r;
    ball.vx = Math.abs(ball.vx);
  } else if (ball.x + ball.r > CANVAS_W) {
    ball.x = CANVAS_W - ball.r;
    ball.vx = -Math.abs(ball.vx);
  }
  if (ball.y - ball.r < 0) {
    ball.y = ball.r;
    ball.vy = Math.abs(ball.vy);
  }

  // Paddle collision
  const px1 = paddle.x - paddle.w / 2;
  const px2 = paddle.x + paddle.w / 2;
  if (
    ball.vy > 0 &&
    ball.y + ball.r >= PADDLE_Y &&
    ball.y + ball.r <= PADDLE_Y + PADDLE_H + Math.abs(ball.vy) &&
    ball.x >= px1 &&
    ball.x <= px2
  ) {
    ball.y = PADDLE_Y - ball.r;
    const hitPos = (ball.x - paddle.x) / (paddle.w / 2);
    const angle = hitPos * (Math.PI / 3);
    const speed = Math.sqrt(ball.vx * ball.vx + ball.vy * ball.vy);
    ball.vx = Math.sin(angle) * speed;
    ball.vy = -Math.cos(angle) * speed;
  }

  // Ball out of bounds
  if (ball.y - ball.r > CANVAS_H) {
    lives--;
    updateHUD();
    if (lives <= 0) {
      gameState = 'gameover';
      showMessage('ゲームオーバー', `スコア: ${score}`, 'もう一度');
    } else {
      resetBall();
    }
  }

  // Brick collisions
  for (let i = bricks.length - 1; i >= 0; i--) {
    const brick = bricks[i];
    if (!rectOverlap(ball, brick)) continue;

    resolveCollision(ball, brick);
    brick.hp--;
    spawnParticles(brick.x + brick.w / 2, brick.y + brick.h / 2, brick.color);

    if (brick.hp <= 0) {
      score += 10 * level;
      bricks.splice(i, 1);
      updateHUD();
    }
    break;
  }

  // Level clear
  if (bricks.length === 0) {
    level++;
    updateHUD();
    if (level > 5) {
      gameState = 'win';
      showMessage('クリア！', `最終スコア: ${score}`, 'もう一度');
    } else {
      initBricks();
      resetBall();
    }
  }

  updateParticles();
}

// Draw helpers
function drawBackground() {
  ctx.fillStyle = '#0a0a1a';
  ctx.fillRect(0, 0, CANVAS_W, CANVAS_H);

  // Subtle grid
  ctx.strokeStyle = 'rgba(255,255,255,0.03)';
  ctx.lineWidth = 1;
  for (let x = 0; x < CANVAS_W; x += 40) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, CANVAS_H);
    ctx.stroke();
  }
  for (let y = 0; y < CANVAS_H; y += 40) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(CANVAS_W, y);
    ctx.stroke();
  }
}

function drawPaddle() {
  const x = paddle.x - paddle.w / 2;
  const y = PADDLE_Y;
  const r = PADDLE_H / 2;

  ctx.shadowColor = '#00e5ff';
  ctx.shadowBlur = 12;

  const grad = ctx.createLinearGradient(x, y, x, y + PADDLE_H);
  grad.addColorStop(0, '#80f0ff');
  grad.addColorStop(1, '#0099bb');
  ctx.fillStyle = grad;

  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + paddle.w - r, y);
  ctx.quadraticCurveTo(x + paddle.w, y, x + paddle.w, y + r);
  ctx.quadraticCurveTo(x + paddle.w, y + PADDLE_H, x + paddle.w - r, y + PADDLE_H);
  ctx.lineTo(x + r, y + PADDLE_H);
  ctx.quadraticCurveTo(x, y + PADDLE_H, x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
  ctx.fill();

  ctx.shadowBlur = 0;
}

function drawBall() {
  ctx.shadowColor = '#ffffff';
  ctx.shadowBlur = 16;

  const grad = ctx.createRadialGradient(
    ball.x - ball.r * 0.3, ball.y - ball.r * 0.3, ball.r * 0.1,
    ball.x, ball.y, ball.r
  );
  grad.addColorStop(0, '#ffffff');
  grad.addColorStop(1, '#aaddff');

  ctx.fillStyle = grad;
  ctx.beginPath();
  ctx.arc(ball.x, ball.y, ball.r, 0, Math.PI * 2);
  ctx.fill();
  ctx.shadowBlur = 0;
}

function drawBricks() {
  const bw = brickWidth();
  for (const brick of bricks) {
    const alpha = brick.hp / brick.maxHp;

    ctx.shadowColor = brick.color.shadow;
    ctx.shadowBlur = 8;

    ctx.fillStyle = brick.color.fill;
    ctx.globalAlpha = 0.3 + alpha * 0.7;

    const r = 4;
    const { x, y, w, h } = brick;
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
    ctx.fill();

    // Highlight
    ctx.globalAlpha = 0.3 * alpha;
    ctx.fillStyle = '#ffffff';
    ctx.beginPath();
    ctx.roundRect(x + 2, y + 2, w - 4, h / 3, [r, r, 0, 0]);
    ctx.fill();

    ctx.globalAlpha = 1;
    ctx.shadowBlur = 0;
  }
}

// Main render
function draw() {
  drawBackground();
  drawBricks();
  drawPaddle();
  drawBall();
  drawParticles();
}

// Game loop
function loop() {
  update();
  draw();
  requestAnimationFrame(loop);
}

// Init
resetGame();
showMessage('ブロック崩し', '矢印キーまたはマウスでパドルを操作', 'スタート');
loop();
