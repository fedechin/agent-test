# Production Setup Guide - Cooperativa Nazareth

## Prerequisites

1. **Server Requirements**
   - Ubuntu 20.04+ or similar Linux distribution
   - Docker and Docker Compose installed
   - Domain name configured with SSL/TLS certificate
   - At least 2GB RAM, 20GB storage

2. **API Keys Required**
   - OpenAI API key
   - Twilio Account SID, Auth Token, and WhatsApp number

## Production Deployment Steps

### 1. Clone Repository and Setup

```bash
git clone <your-repository-url>
cd agent-test

# Copy environment template
cp .env.example .env

# Edit production environment variables
nano .env
```

### 2. Configure Environment Variables

Edit `.env` file with production values:

```env
# OpenAI Configuration
OPENAI_API_KEY=sk-your_actual_openai_api_key

# Twilio Configuration
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_actual_auth_token
TWILIO_WHATSAPP_FROM=whatsapp:+your_twilio_whatsapp_number

# Database Configuration (PostgreSQL for production)
DATABASE_URL=postgresql://nazareth_user:STRONG_PASSWORD_HERE@db:5432/nazareth_conversations

# Security Configuration
SECRET_KEY=GENERATE_A_VERY_LONG_RANDOM_STRING_HERE

# Application Configuration
ENVIRONMENT=production
```

### 3. Update Docker Compose for Production

Update `docker-compose.yml` database password:

```yaml
environment:
  POSTGRES_PASSWORD: SAME_STRONG_PASSWORD_AS_IN_DATABASE_URL
```

### 4. Deploy Application

```bash
# Build and start services
docker-compose up --build -d

# Check logs
docker-compose logs -f agent

# Verify database is running
docker-compose logs db
```

### 5. Create First Admin User

```bash
# Run the admin creation script
python3 create_admin.py
```

Follow prompts to create your first human agent account.

### 6. Configure Reverse Proxy (Nginx)

Create `/etc/nginx/sites-available/nazareth-agent`:

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable site and restart Nginx:

```bash
sudo ln -s /etc/nginx/sites-available/nazareth-agent /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### 7. Configure SSL with Let's Encrypt

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

### 8. Configure Twilio Webhook

In Twilio Console:
1. Go to Phone Numbers → Manage → WhatsApp senders
2. Select your WhatsApp number
3. Set webhook URL to: `https://your-domain.com/whatsapp`
4. Set HTTP method to POST

### 9. Test System

1. **Test WhatsApp Integration**
   - Send message to your Twilio WhatsApp number
   - Verify response from RAG system

2. **Test Human Handover**
   - Send message like "quiero hablar con humano"
   - Verify conversation appears in admin dashboard

3. **Test Admin Dashboard**
   - Visit `https://your-domain.com/admin`
   - Log in with created admin account
   - Test taking conversations and sending responses

## Security Considerations

### 1. Database Security
- Use strong PostgreSQL password
- Restrict database port access (remove port mapping in production)
- Regular database backups

### 2. Application Security
- Generate strong SECRET_KEY (32+ characters)
- Use HTTPS only in production
- Implement rate limiting for API endpoints
- Regular security updates

### 3. Twilio Security
- Verify webhook signatures
- Use HTTPS for all webhook URLs
- Monitor usage and billing

## Monitoring and Maintenance

### 1. Log Management

```bash
# View application logs
docker-compose logs -f agent

# View database logs
docker-compose logs -f db
```

### 2. Database Backups

```bash
# Backup database
docker-compose exec db pg_dump -U nazareth_user nazareth_conversations > backup_$(date +%Y%m%d).sql

# Restore database
docker-compose exec -T db psql -U nazareth_user nazareth_conversations < backup_file.sql
```

### 3. Updates

```bash
# Pull latest changes
git pull origin main

# Rebuild and restart
docker-compose down
docker-compose up --build -d
```

## Troubleshooting

### Common Issues

1. **WhatsApp messages not being received**
   - Check Twilio webhook configuration
   - Verify webhook URL is accessible from internet
   - Check application logs for errors

2. **Database connection errors**
   - Verify PostgreSQL is running: `docker-compose ps`
   - Check database credentials in `.env`
   - Verify database is accepting connections

3. **Admin dashboard not accessible**
   - Check if admin user exists: `python3 create_admin.py`
   - Verify templates directory is mounted
   - Check application logs for authentication errors

### Performance Optimization

1. **Vector Store Optimization**
   - Ensure FAISS index is properly built
   - Monitor vector store query performance
   - Consider index rebuilding if documents change

2. **Database Performance**
   - Monitor conversation and message table sizes
   - Implement data archiving for old conversations
   - Add database indexes for frequently queried fields

## Scaling Considerations

### Horizontal Scaling
- Use load balancer for multiple app instances
- Implement session affinity for WebSocket connections
- Consider Redis for session management

### Database Scaling
- PostgreSQL read replicas for analytics
- Connection pooling with PgBouncer
- Database partitioning for large message tables

## Support and Maintenance

### Regular Tasks
- [ ] Weekly database backups
- [ ] Monthly security updates
- [ ] Quarterly performance reviews
- [ ] Annual security audits

### Monitoring Alerts
- Set up alerts for:
  - High error rates
  - Database connection issues
  - Disk space usage
  - Twilio API failures

For support, check application logs and refer to the troubleshooting section above.