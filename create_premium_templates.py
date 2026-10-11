import os

out_dir = "premium_email_templates"
os.makedirs(out_dir, exist_ok=True)

templates = []

# Template 1: SaaS / Tech (Stripe/Notion inspired)
templates.append({
    "name": "01_Tech_SaaS_Welcome",
    "html": """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Welcome to Our Platform</title>
    <style>
        body { margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background-color: #f6f9fc; -webkit-font-smoothing: antialiased; }
        .wrapper { width: 100%; table-layout: fixed; background-color: #f6f9fc; padding-bottom: 40px; }
        .main { background-color: #ffffff; margin: 40px auto; max-width: 600px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); overflow: hidden; }
        .header { padding: 40px 40px 20px; text-align: left; }
        .logo { width: 120px; height: auto; }
        .content { padding: 0 40px 40px; color: #425466; line-height: 1.6; font-size: 16px; }
        h1 { color: #0a2540; font-size: 24px; font-weight: 600; margin-bottom: 20px; }
        .button { display: inline-block; background-color: #635bff; color: #ffffff; text-decoration: none; padding: 12px 24px; border-radius: 4px; font-weight: 500; font-size: 16px; margin-top: 20px; transition: background-color 0.2s; }
        .button:hover { background-color: #4b45cf; }
        .footer { text-align: center; padding: 20px 40px; color: #8898aa; font-size: 13px; background-color: #f6f9fc; }
        .footer a { color: #635bff; text-decoration: none; }
    </style>
</head>
<body>
    <table class="wrapper" width="100%" cellpadding="0" cellspacing="0" role="presentation">
        <tr>
            <td align="center">
                <table class="main" width="100%" max-width="600" cellpadding="0" cellspacing="0" role="presentation">
                    <tr>
                        <td class="header">
                            <img src="https://via.placeholder.com/120x40/0a2540/ffffff?text=LOGO" alt="Logo" class="logo">
                        </td>
                    </tr>
                    <tr>
                        <td class="content">
                            <h1>Welcome to the future of work.</h1>
                            <p>Hi {{ contact.firstname | default('there') }},</p>
                            <p>We're thrilled to have you on board. Our platform is designed to help your team move faster, stay aligned, and build better products together.</p>
                            <p>To get the most out of your account, we recommend starting with our 3-minute quickstart guide.</p>
                            <a href="#" class="button">Explore the Quickstart Guide</a>
                            <p style="margin-top: 30px; font-size: 14px; color: #8898aa;">Need help? Reply to this email and our support team will jump right in.</p>
                        </td>
                    </tr>
                </table>
                <table width="100%" max-width="600" cellpadding="0" cellspacing="0" role="presentation">
                    <tr>
                        <td class="footer">
                            <p>&copy; 2026 Your SaaS Company. All rights reserved.<br>
                            123 Innovation Drive, San Francisco, CA 94107</p>
                            <p><a href="#">Unsubscribe</a> &bull; <a href="#">Privacy Policy</a></p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""
})

# Template 2: E-Commerce (Nike/Fashion inspired)
templates.append({
    "name": "02_Ecommerce_Visual",
    "html": """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>New Arrivals Are Here</title>
    <style>
        body { margin: 0; padding: 0; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; background-color: #ffffff; }
        .main { max-width: 600px; margin: 0 auto; background-color: #ffffff; }
        .hero { width: 100%; height: auto; display: block; }
        .text-center { text-align: center; padding: 40px 20px; }
        h1 { font-size: 32px; text-transform: uppercase; letter-spacing: 2px; margin: 0 0 15px; font-weight: 700; color: #111; }
        p { color: #555; font-size: 16px; line-height: 1.5; margin: 0 0 25px; }
        .btn-dark { display: inline-block; background-color: #111; color: #fff; text-decoration: none; padding: 15px 30px; text-transform: uppercase; font-weight: bold; letter-spacing: 1px; }
        .grid { width: 100%; padding: 0 10px; }
        .grid td { padding: 10px; width: 50%; vertical-align: top; text-align: center; }
        .product-img { width: 100%; height: auto; background-color: #f4f4f4; }
        .product-name { font-weight: bold; margin: 15px 0 5px; font-size: 16px; color: #111; }
        .product-price { color: #777; margin: 0 0 15px; font-size: 14px; }
        .footer { background-color: #111; color: #fff; text-align: center; padding: 40px 20px; margin-top: 40px; }
        .footer p { color: #999; font-size: 12px; }
    </style>
</head>
<body>
    <table class="main" width="100%" cellpadding="0" cellspacing="0" role="presentation">
        <tr>
            <td align="center" style="padding: 20px 0;">
                <img src="https://via.placeholder.com/100x40/ffffff/111111?text=BRAND" alt="Brand" width="100">
            </td>
        </tr>
        <tr>
            <td>
                <img src="https://images.unsplash.com/photo-1556906781-9a412961c28c?auto=format&fit=crop&w=600&q=80" alt="Hero Collection" class="hero">
            </td>
        </tr>
        <tr>
            <td class="text-center">
                <h1>The Fall Collection</h1>
                <p>Designed for the elements. Engineered for the streets. Meet our most versatile collection yet.</p>
                <a href="#" class="btn-dark">Shop Now</a>
            </td>
        </tr>
        <tr>
            <td>
                <table class="grid" width="100%" cellpadding="0" cellspacing="0" role="presentation">
                    <tr>
                        <td>
                            <img src="https://images.unsplash.com/photo-1542291026-7eec264c27ff?auto=format&fit=crop&w=280&q=80" alt="Shoe 1" class="product-img">
                            <p class="product-name">Phantom X</p>
                            <p class="product-price">$120.00</p>
                            <a href="#" style="color:#111; font-weight:bold; text-decoration:underline;">Shop</a>
                        </td>
                        <td>
                            <img src="https://images.unsplash.com/photo-1508985160275-c9676e1a7428?auto=format&fit=crop&w=280&q=80" alt="Shoe 2" class="product-img">
                            <p class="product-name">Apex Runner</p>
                            <p class="product-price">$145.00</p>
                            <a href="#" style="color:#111; font-weight:bold; text-decoration:underline;">Shop</a>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
        <tr>
            <td class="footer">
                <p>BRAND INC. &copy; 2026<br>456 Fashion Ave, New York, NY 10001</p>
                <p><a href="#" style="color: #fff;">Unsubscribe</a> | <a href="#" style="color: #fff;">Web View</a></p>
            </td>
        </tr>
    </table>
</body>
</html>"""
})

# Template 3: Modern Newsletter (Morning Brew / Substack inspired)
templates.append({
    "name": "03_Modern_Newsletter",
    "html": """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Daily Briefing</title>
    <style>
        body { margin: 0; padding: 0; font-family: Georgia, serif; background-color: #f9f9f9; color: #222222; }
        .wrapper { background-color: #f9f9f9; padding: 20px 0; }
        .main { max-width: 600px; margin: 0 auto; background-color: #ffffff; border-top: 6px solid #ff4500; }
        .header { text-align: center; padding: 30px 20px; border-bottom: 1px solid #eeeeee; }
        .date { font-family: Helvetica, Arial, sans-serif; font-size: 12px; color: #888; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 10px; display: block; }
        .logo { font-size: 28px; font-weight: bold; font-family: Helvetica, Arial, sans-serif; color: #111; margin: 0; }
        .content { padding: 30px 40px; font-size: 18px; line-height: 1.7; }
        h2 { font-family: Helvetica, Arial, sans-serif; font-size: 22px; color: #111; margin-top: 30px; }
        .highlight { background-color: #fff3cd; padding: 2px 4px; }
        .divider { height: 1px; background-color: #eeeeee; margin: 40px 0; }
        .ad-box { border: 1px solid #e0e0e0; padding: 20px; background-color: #fafafa; margin: 30px 0; font-family: Helvetica, Arial, sans-serif; font-size: 14px; }
        .footer { padding: 30px 40px; text-align: center; font-family: Helvetica, Arial, sans-serif; font-size: 12px; color: #777; background-color: #ffffff; border-top: 1px solid #eeeeee; }
    </style>
</head>
<body>
    <table class="wrapper" width="100%" cellpadding="0" cellspacing="0" role="presentation">
        <tr>
            <td>
                <table class="main" width="100%" cellpadding="0" cellspacing="0" role="presentation">
                    <tr>
                        <td class="header">
                            <span class="date">Tuesday, September 15</span>
                            <h1 class="logo">THE DAILY BRIEF</h1>
                        </td>
                    </tr>
                    <tr>
                        <td class="content">
                            <p>Good morning!</p>
                            <p>Today we're diving into the sudden shift in global markets, what the new AI regulations mean for your startup, and why <span class="highlight">everyone is talking about remote work again.</span></p>
                            
                            <h2>1. The Markets Take a Turn</h2>
                            <p>After a three-week rally, tech stocks took a breather yesterday. Analysts suggest this is a natural correction, but underlying data shows a shift in consumer spending habits leading up to the holiday season.</p>
                            <p><strong>What it means:</strong> If you're running a B2C company, expect slightly higher customer acquisition costs over the next 45 days.</p>
                            
                            <div class="ad-box">
                                <strong>SPONSORED BY CLOUDSCALE</strong><br><br>
                                Stop paying for server capacity you don't use. CloudScale's dynamic infrastructure automatically scales down when you're asleep, saving startups an average of 40% on AWS bills. <a href="#" style="color: #ff4500; font-weight:bold;">Try it free for 30 days.</a>
                            </div>

                            <h2>2. The Return to Office... Again</h2>
                            <p>Several Fortune 500 companies announced updated RTO mandates this week, requiring employees in the office 4 days a week. The pushback from employees has been swift, with internal petitions circulating widely.</p>

                            <div class="divider"></div>
                            
                            <p style="font-family: Helvetica, Arial, sans-serif; font-size: 15px; text-align:center;">
                                <em>Enjoying today's brief? Share it with a colleague!</em><br>
                                <a href="#" style="color:#ff4500; text-decoration:none; font-weight:bold;">Forward to a friend &rarr;</a>
                            </p>
                        </td>
                    </tr>
                    <tr>
                        <td class="footer">
                            <p>You received this email because you signed up on our website.</p>
                            <p><a href="#" style="color:#777;">Update preferences</a> | <a href="#" style="color:#777;">Unsubscribe</a></p>
                            <p>The Daily Brief &copy; 2026<br>789 Media Blvd, Chicago, IL 60601</p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""
})

# Template 4: Product Launch / Apple Inspired
templates.append({
    "name": "04_Product_Launch_Premium",
    "html": """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Introducing Product X</title>
    <style>
        body { margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background-color: #000000; color: #ffffff; }
        .main { max-width: 600px; margin: 0 auto; background-color: #000000; text-align: center; }
        .header { padding: 30px; }
        .title { font-size: 48px; font-weight: 700; letter-spacing: -1px; margin: 20px 0 10px; background: -webkit-linear-gradient(#fff, #999); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .subtitle { font-size: 24px; color: #a1a1a6; margin: 0 0 30px; font-weight: 400; }
        .hero-img { width: 100%; max-width: 500px; height: auto; margin: 0 auto 30px; display: block; border-radius: 20px; box-shadow: 0 20px 40px rgba(255,255,255,0.1); }
        .btn-buy { display: inline-block; background-color: #ffffff; color: #000000; text-decoration: none; padding: 12px 30px; border-radius: 30px; font-weight: 600; font-size: 16px; margin: 10px; }
        .btn-learn { display: inline-block; background-color: transparent; color: #2997ff; text-decoration: none; font-size: 16px; margin: 10px; padding: 12px; }
        .feature-grid { margin-top: 50px; padding: 0 20px; }
        .feature-grid td { padding: 20px; width: 50%; vertical-align: top; }
        .feature-icon { font-size: 30px; margin-bottom: 10px; display: block; }
        .feature-title { font-size: 18px; font-weight: 600; margin-bottom: 5px; }
        .feature-text { font-size: 14px; color: #a1a1a6; line-height: 1.5; }
        .footer { padding: 50px 20px; border-top: 1px solid #333; margin-top: 50px; font-size: 12px; color: #666; }
    </style>
</head>
<body>
    <table class="main" width="100%" cellpadding="0" cellspacing="0" role="presentation">
        <tr>
            <td class="header">
                <img src="https://via.placeholder.com/40x40/000000/ffffff?text=X" alt="Logo" width="40" style="border-radius: 8px;">
                <h1 class="title">Pro Vision.</h1>
                <h2 class="subtitle">Welcome to the spatial era.</h2>
                <img src="https://images.unsplash.com/photo-1616423640778-28d1b53229bd?auto=format&fit=crop&w=800&q=80" alt="Product" class="hero-img">
                <br>
                <a href="#" class="btn-buy">Pre-order now</a>
                <a href="#" class="btn-learn">Learn more &gt;</a>
            </td>
        </tr>
        <tr>
            <td>
                <table class="feature-grid" width="100%" cellpadding="0" cellspacing="0" role="presentation">
                    <tr>
                        <td>
                            <span class="feature-icon">✨</span>
                            <div class="feature-title">Ultra HD Display</div>
                            <div class="feature-text">23 million pixels across two displays. A visual experience unlike any other.</div>
                        </td>
                        <td>
                            <span class="feature-icon">🚀</span>
                            <div class="feature-title">M-Class Chip</div>
                            <div class="feature-text">Dual-chip design for unparalleled real-time processing performance.</div>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
        <tr>
            <td class="footer">
                <p>Copyright &copy; 2026 TechCorp Inc. All rights reserved.</p>
                <p><a href="#" style="color:#666;">Privacy Policy</a> | <a href="#" style="color:#666;">Terms of Use</a> | <a href="#" style="color:#666;">Unsubscribe</a></p>
            </td>
        </tr>
    </table>
</body>
</html>"""
})

for t in templates:
    file_path = os.path.join(out_dir, f"{t['name']}.html")
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(t['html'])
    print(f"Created: {file_path}")

print("Premium templates created successfully!")
