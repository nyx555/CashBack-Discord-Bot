# Discord Cashback Bot

A feature-rich Discord bot that manages cashback rewards, withdrawals, and user profiles with a modern UI and robust security features.

## Features

### Core Features
- 💰 Cashback code redemption system
- 💳 Withdrawal request management
- 👤 User profiles with levels and ranks
- 📜 Transaction history tracking
- 🔔 Automated notifications
- 🛡️ Enhanced security measures
- 📊 System statistics and analytics

### User Features
- View current balance
- Redeem cashback codes
- Submit withdrawal requests
- Check transaction history
- View detailed profile
- Track earnings and withdrawals
- View transaction status updates
- Receive automated notifications

### Staff Features
- Generate cashback codes
- Manage withdrawal requests
- View transaction logs
- Monitor user activity
- Handle user support
- View system statistics
- Filter codes by status
- Track code redemption history
- Manage withdrawal channels
- View detailed analytics

### Security Features
- Rate limiting for all actions
- Transaction verification
- Secure withdrawal process
- Permission-based access control
- Anti-abuse measures
- Automatic refunds for rejected withdrawals
- Transaction ID tracking
- Staff action logging

## Setup

1. Clone the repository
2. Install required packages:
```bash
pip install -r requirements.txt
```

3. Set up environment variables:
```env
DISCORD_TOKEN=your_discord_bot_token
MONGODB_URI=your_mongodb_connection_string
```

4. Run the bot:
```bash
python main.py
```

## Commands

### User Commands
- `$panel` - Display the cashback panel (Staff only)
- `$transactions [page]` - View transaction history with pagination
- `$profile [user]` - View user profile (your own or another user's)

### Staff Commands
- `$generate_code <amount>` - Generate a new cashback code
- `$view_codes [status]` - View all codes (active/redeemed/all)
- `$view_withdrawals [status]` - View withdrawal requests (pending/completed/rejected)
- `$stats` - View system-wide statistics and analytics

## Database Schema

### Users Collection
```json
{
    "user_id": "string",
    "balance": "float",
    "total_earned": "float",
    "total_withdrawn": "float",
    "created_at": "datetime",
    "last_transaction": "datetime",
    "transaction_count": "integer"
}
```

### User Profiles Collection
```json
{
    "user_id": "string",
    "level": "integer",
    "xp": "integer",
    "rank": "string",
    "achievements": "array",
    "last_activity": "datetime"
}
```

### Transactions Collection
```json
{
    "user_id": "string",
    "amount": "float",
    "type": "string",
    "status": "string",
    "timestamp": "datetime",
    "transaction_id": "string"
}
```

### Codes Collection
```json
{
    "code": "string",
    "amount": "float",
    "redeemed": "boolean",
    "created_at": "datetime",
    "created_by": "string",
    "redeemed_by": "string",
    "redeemed_at": "datetime"
}
```

## Rate Limits
- Code redemption: 5 attempts per minute
- Withdrawals: 3 attempts per hour
- Balance/profile checks: 10 attempts per minute

## Level System
- Earn XP for each transaction (1 XP per dollar)
- Level up every 1000 XP
- Ranks: Bronze → Silver → Gold → Platinum → Diamond
- Rank upgrades every 5 levels

## Withdrawal Process
1. User submits withdrawal request
2. System creates private channel
3. Staff reviews request
4. Staff approves/rejects
5. User receives notification
6. Channel is locked after completion

## Error Handling
- Missing permissions
- Invalid arguments
- Command not found
- Rate limit exceeded
- Insufficient balance
- Invalid codes
- Database errors

## Contributing
Contributions are welcome! Please feel free to submit a Pull Request.

## License
This project is licensed under the MIT License - see the LICENSE file for details. 