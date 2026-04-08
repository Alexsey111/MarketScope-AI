# MarketScope AI

> **AI-powered marketplace product analysis platform with scoring engine v4.0**

MarketScope AI — enterprise-grade SaaS платформа для анализа товарных карточек маркетплейсов с использованием LLM (настраиваемая модель через `MODEL_NAME`, по умолчанию `gpt-4o-mini`) и кастомного скорингового движка. Включает REST API, Telegram-бота, асинхронную обработку через Celery и multi-tenant архитектуру.

---

## 🚀 **Ключевые возможности**

### **1. Intelligent Analysis Pipeline**
- 🤖 **LLM-powered analysis** — OpenAI-модель анализирует карточку товара и генерирует структурированные метрики
- 📊 **Advanced Scoring Engine v4** — нелинейные логистические кривые, композитная оценка рисков
- 🎯 **Multi-dimensional scoring**:
  - Product Score (completeness, SEO, USP, visual quality)
  - Market Score (competition, differentiation, demand)
  - Platform Score (price alignment, category maturity)
  - Growth Score (margins, upsell, repeat purchase)
- 🔒 **Security-first** — prompt injection protection, input sanitization, rate limiting

### **2. Multi-tenant SaaS Architecture**
- 👥 **Tenant isolation** — полная изоляция данных между организациями
- 🎫 **Subscription plans** — Free, Starter, Professional, Business, Enterprise
- 📈 **Usage quotas**:
  - Analyses per month
  - Requests per minute
  - Tokens per day
- 🔐 **JWT Authentication** — secure access tokens with role-based access control

### **3. Async Processing & Scaling**
- ⚡ **Celery task queue** — асинхронный анализ, batch processing
- 📦 **Redis caching** — кеширование результатов анализов (1 час TTL)
- 🔄 **Retry mechanism** — автоматический retry failed tasks
- 📊 **Usage tracking** — детальная статистика использования

### **4. Multiple Interfaces**
- 🌐 **REST API** — FastAPI с OpenAPI/Swagger документацией
- 💬 **Telegram Bot** — простой UX для быстрого анализа
- 📱 **Webhook support** — интеграция с внешними системами

---

## 🏗️ **Tech Stack**

| Component | Technology |
|-----------|-----------|
| **Backend** | Python 3.11+, FastAPI, Pydantic |
| **Database** | PostgreSQL 15+ (multi-tenant) |
| **Cache** | Redis 7+ |
| **Queue** | Celery + Redis broker |
| **AI/ML** | OpenAI API (configurable model), scikit-learn |
| **Auth** | JWT (python-jose), bcrypt (passlib) |
| **Bot** | Aiogram 3.x |
| **Migrations** | Alembic |
| **Container** | Docker, Docker Compose |

---

## 📁 **Project Structure**

```
MarketScope AI/
├── api/                          # FastAPI приложение
│   ├── main.py                   # Точка входа API
│   └── routers/                  # API эндпоинты
│       ├── auth.py               # JWT авторизация
│       ├── analysis.py           # Основной анализ
│       ├── tenant_analyses.py    # Multi-tenant CRUD
│       ├── async_analysis.py     # Асинхронные задачи
│       └── celery_analysis.py    # Управление Celery задачами
│
├── app/                          # Ядро приложения
│   ├── core/                     # Бизнес-логика
│   │   ├── scoring_v4.py         # 🎯 Scoring Engine V4 (источник истины)
│   │   ├── calibration.py        # Калибровка оценок
│   │   └── llm_wrapper.py        # LLM абстракция
│   ├── models/                   # Pydantic модели
│   │   └── job.py                # Модели задач
│   └── tasks/                    # Celery задачи
│       └── analysis_tasks.py     # Задачи анализа
│
├── services/                     # Сервисный слой
│   ├── models.py                 # 🗄️ SQLAlchemy модели (единый источник)
│   ├── tenant_service.py         # Multi-tenant CRUD
│   ├── auth.py                   # Зависимости авторизации
│   ├── jwt_handler.py            # JWT операции
│   ├── subscription.py           # Квоты и лимиты
│   ├── llm_service.py            # OpenAI API враппер
│   ├── scoring_engine.py         # Построение промптов
│   ├── cache.py                  # Redis кеш
│   ├── rate_limiter.py           # Rate limiting
│   ├── usage_tracker.py          # Статистика использования
│   ├── security.py               # Логирование безопасности
│   └── database.py               # История анализов
│
├── bot/                          # Telegram бот
│   ├── handlers.py               # Обработчики команд
│   ├── keyboards.py              # Клавиатуры бота
│   └── states.py                 # FSM состояния
│
├── alembic/                      # Alembic миграции
│   ├── env.py                    # Конфиг Alembic
│   └── versions/                 # Файлы миграций
│
├── celery_app.py                 # Конфигурация Celery
├── config.py                     # Конфигурация приложения
├── main.py                       # Точка входа бота
├── requirements.txt              # Python зависимости
├── Dockerfile                    # Docker образ
├── docker-compose.yml            # Multi-container setup
└── README.md                     # Этот файл
```

---

## 🚀 **Quick Start**

### **1. Prerequisites**

- Python 3.11+
- PostgreSQL 15+
- Redis 7+
- OpenAI API key
- (Optional) Telegram bot token

### **2. Clone & Install**

```bash
git clone <repository-url>
cd "MarketScope AI"

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# or .venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt
```

### **3. Environment Setup**

Create `.env` file:

```env
# OpenAI
OPENAI_API_KEY=sk-your-key-here
MODEL_NAME=gpt-4o-mini

# Database
DATABASE_URL=postgresql://user:password@localhost:5432/marketscope

# Redis
REDIS_URL=redis://localhost:6379/0

# JWT
SECRET_KEY=your-secret-key-change-in-production
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7

# Subscription Limits
FREE_DAILY_LIMIT=5
PRO_DAILY_LIMIT=100

# Telegram Bot (optional)
BOT_TOKEN=your-telegram-bot-token
```

### **4. Database Initialization**

```bash
# Run migrations
alembic upgrade head

# Or initialize manually (first time only)
python -c "from services.tenant_service import init_db; init_db()"
```

### **5. Start Services**

**Option A: Docker Compose (Recommended)**

```bash
docker-compose up -d
```

This starts:
- PostgreSQL (port 5432)
- Redis (port 6379)
- FastAPI (port 8000)
- Celery worker

**Option B: Manual**

Terminal 1 - API:
```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

Terminal 2 - Celery Worker:
```bash
celery -A celery_app.celery_app worker -l info
```

Terminal 3 - Telegram Bot (optional):
```bash
python main.py
```

---

## 📚 **API Documentation**

After starting the API, visit:

- **Swagger**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Health Check**: http://localhost:8000/health

### **Key Endpoints**

### Authentication

```bash
# Register
POST /auth/register
{
  "email": "user@example.com",
  "password": "SecurePass123",
  "tenant_name": "My Company"
}

# Login
POST /auth/login
{
  "email": "user@example.com",
  "password": "SecurePass123"
}

# Response
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "refresh_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "token_type": "bearer"
}
```

### Analysis

```bash
# Analyze product card
POST /api/analysis
Authorization: Bearer {access_token}
{
  "title": "Смартфон Samsung Galaxy S24",
  "description": "Флагманский смартфон с камерой 200MP...",
  "user_id": 1
}

# Response
{
  "niche": "electronics",
  "scoring": {
    "product_score": 78.5,
    "market_score": 65.2,
    "platform_score": 82.1,
    "growth_score": 71.3,
    "risk_penalty": 12.5,
    "risk_flags": ["high_competition"],
    "final_score": 71.7,
    "confidence_score": 84.2,
    "scoring_version": "v4.0"
  },
  "analysis": {
    "scoring_metrics": {...},
    "strengths": ["Strong brand", "High demand"],
    "weaknesses": ["High competition", "Price sensitivity"],
    "recommendations": ["Focus on differentiation", "Build unique value proposition"]
  }
}
```

### Async Analysis

```bash
# Create async task
POST /api/async/analyses
Authorization: Bearer {access_token}
{
  "title": "Product title",
  "description": "Product description"
}

# Get task status
GET /api/async/analyses/{task_id}
Authorization: Bearer {access_token}
```

### Batch Analysis

```bash
POST /api/analysis/batch
{
  "items": [
    {"id": "item_1", "title": "...", "description": "..."},
    {"id": "item_2", "title": "...", "description": "..."}
  ]
}

# Get batch result
GET /api/analysis/batch/{task_id}
```

---

## 🎯 **Scoring Engine v4.0**

### Architecture

The scoring engine uses non-linear logistic curves for more realistic score distributions:

```python
# Logistic transformation
score = 100 / (1 + exp(-k * (x - x₀)))

# Where:
# k = steepness (0.1-0.2)
# x₀ = inflection point (50)
# x = raw metric (0-100)
```

### Score Components

| Component | Weight | Factors |
|-----------|--------|---------|
| Product Score | 35% | Completeness (25%), SEO (20%), USP (20%), Visual (20%), Price (15%) |
| Market Score | 30% | Competition (30%), Differentiation (30%), Entry Barrier (20%), Demand (20%) |
| Platform Score | 20% | Price Alignment (30%), Category Maturity (25%), Brand Dependency (25%), Logistics (20%) |
| Growth Score | 15% | Margin (40%), Upsell (20%), Repeat Purchase (20%), Expansion (20%) |

### Risk Model

```python
# Composite risk calculation
risk = min(40, margin_risk + competition_risk + interaction_risk)

# Triple interaction penalty
if margin < 15% AND competition > 70% AND differentiation < 40%:
    risk += 25  # Critical market risk
```

---

## 🔐 **Security**

### Implemented Protections

✅ JWT Authentication — HS256 signed tokens  
✅ Password Hashing — bcrypt with salt  
✅ Rate Limiting — sliding window (Redis)  
✅ Request Size Limits — max 100KB body  
✅ Prompt Injection Protection — sanitization + security prompts  
✅ Input Validation — Pydantic strict models  
✅ CORS — configurable origins  
✅ Security Headers — X-Frame-Options, CSP  
✅ SQL Injection Prevention — SQLAlchemy ORM  
✅ Sensitive Data Masking — sanitized logs

---

## 📊 **Subscription Plans**

| Plan | Analyses/Month | Rate Limit | Tokens/Day | Price |
|------|----------------|------------|------------|-------|
| Free | 5 | 5 req/min | 10K | $0 |
| Starter | 20 | 20 req/min | 50K | $29 |
| Professional | 100 | 60 req/min | 200K | $99 |
| Business | 1,000 | 120 req/min | 1M | $499 |
| Enterprise | Unlimited | Unlimited | Unlimited | Custom |

---

## 🧪 **Testing**

```bash
# Run tests
pytest

# With coverage
pytest --cov=. --cov-report=html

# Specific test
pytest tests/test_scoring.py -v
```

---

## 📦 **Production Deployment**

### Docker Compose Production

```bash
# Build and start
docker-compose -f docker-compose.prod.yml up -d

# View logs
docker-compose logs -f api

# Scale workers
docker-compose up -d --scale celery=3
```

### Environment Variables (Production)

```env
# Security
SECRET_KEY=<generate-with-openssl-rand-hex-32>
ALGORITHM=HS256

# Database
DATABASE_URL=postgresql://user:secure_password@db:5432/marketscope

# Redis
REDIS_URL=redis://:redis_password@redis:6379/0

# OpenAI
OPENAI_API_KEY=sk-prod-key

# Monitoring
SENTRY_DSN=https://...
```

---

## 🐛 **Troubleshooting**

### Common Issues

**1. Celery tasks not running**

```bash
# Check Redis connection
redis-cli ping

# Check Celery worker logs
celery -A celery_app.celery_app worker -l debug
```

**2. Database connection errors**

```bash
# Test connection
psql -h localhost -U user -d marketscope

# Run migrations
alembic upgrade head
```

**3. LLM timeouts**

```python
# Increase timeout in config.py
LLM_TIMEOUT = 30  # seconds
```

---

## 📈 **Monitoring**

**Celery Monitoring (Flower)**

```bash
celery -A celery_app flower --port=5555
```

Visit: http://localhost:5555

### Health Checks

```bash
# API health
curl http://localhost:8000/health

# Celery health
curl http://localhost:8000/celery/health
```

---

## 🤝 **Contributing**

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

---

## 📝 **License**

MIT License - see LICENSE file for details

---

## 🆘 **Support**

- 📧 Email: support@marketscope.ai
- 💬 Telegram: @marketscope_support
- 📖 Docs: https://docs.marketscope.ai

---

## 🚧 **Roadmap**

- [ ] GraphQL API
- [ ] Real-time analysis via WebSockets
- [ ] ML model fine-tuning on user feedback
- [ ] Browser extension
- [ ] Mobile app (React Native)
- [ ] Advanced analytics dashboard
- [ ] A/B testing framework
- [ ] Competitor tracking
