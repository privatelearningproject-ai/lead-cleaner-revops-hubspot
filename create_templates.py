import os

boilerplate = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{title}</title>
    <style>
        body {{ font-family: Arial, sans-serif; background-color: #f4f4f4; margin: 0; padding: 20px; }}
        .container {{ background-color: #ffffff; max-width: 600px; margin: 0 auto; padding: 20px; border-radius: 8px; }}
        .header {{ text-align: center; padding-bottom: 20px; border-bottom: 1px solid #eeeeee; }}
        .content {{ padding: 20px 0; line-height: 1.6; color: #333333; }}
        .footer {{ text-align: center; font-size: 12px; color: #999999; padding-top: 20px; border-top: 1px solid #eeeeee; }}
        .button {{ display: inline-block; padding: 10px 20px; background-color: #007bff; color: #ffffff; text-decoration: none; border-radius: 4px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>{title}</h2>
        </div>
        <div class="content">
            {body}
        </div>
        <div class="footer">
            <p>Your Company Name<br>123 Business Rd, City</p>
            <p>You received this email because you are subscribed to our list.</p>
            <p><a href="#">Unsubscribe</a> | <a href="#">Manage Preferences</a></p>
        </div>
    </div>
</body>
</html>
"""

templates = [
    {
        "name": "01_Welcome_Email",
        "title": "Welcome to Our Community!",
        "body": "<p>Hi [Name],</p><p>We are thrilled to have you on board! Here's a quick overview of what you can expect from us.</p><br><a href='#' class='button'>Get Started</a>"
    },
    {
        "name": "02_Monthly_Newsletter",
        "title": "Your Monthly Update",
        "body": "<p>Hello [Name],</p><p>Here are the top stories and updates from this month.</p><ul><li>Update 1</li><li>Update 2</li></ul><br><a href='#' class='button'>Read More</a>"
    },
    {
        "name": "03_Promotional_Offer",
        "title": "Special Offer Just For You",
        "body": "<p>Hi [Name],</p><p>Enjoy 20% off your next purchase using the code <strong>SAVE20</strong>.</p><br><a href='#' class='button'>Shop Now</a>"
    },
    {
        "name": "04_Product_Announcement",
        "title": "Introducing Our New Feature",
        "body": "<p>We're excited to announce the launch of our newest feature designed to make your life easier.</p><br><a href='#' class='button'>Learn More</a>"
    },
    {
        "name": "05_Abandoned_Cart",
        "title": "You Left Something Behind",
        "body": "<p>Hi [Name],</p><p>We noticed you left some great items in your cart. Complete your purchase now before they sell out!</p><br><a href='#' class='button'>Return to Cart</a>"
    },
    {
        "name": "06_Event_Invitation",
        "title": "You're Invited: Exclusive Webinar",
        "body": "<p>Join us for an exclusive webinar where we discuss industry trends and strategies.</p><p><strong>Date:</strong> [Date]<br><strong>Time:</strong> [Time]</p><br><a href='#' class='button'>RSVP Now</a>"
    },
    {
        "name": "07_Re-engagement",
        "title": "We Miss You!",
        "body": "<p>Hi [Name],</p><p>It's been a while since we last saw you. Come back and check out what's new!</p><br><a href='#' class='button'>See What's New</a>"
    },
    {
        "name": "08_Customer_Feedback",
        "title": "How did we do?",
        "body": "<p>Your opinion matters to us. Please take a moment to share your feedback about your recent experience.</p><br><a href='#' class='button'>Take the Survey</a>"
    },
    {
        "name": "09_Order_Confirmation",
        "title": "Thank You For Your Order",
        "body": "<p>Hi [Name],</p><p>Your order has been received and is currently being processed. We will notify you once it ships.</p><br><a href='#' class='button'>View Order Status</a>"
    },
    {
        "name": "10_Holiday_Greeting",
        "title": "Happy Holidays!",
        "body": "<p>Wishing you and yours a joyful holiday season and a happy New Year!</p><br><a href='#' class='button'>Visit Our Store</a>"
    },
    {
        "name": "11_Flash_Sale",
        "title": "24-Hour Flash Sale Starts Now!",
        "body": "<p>Hi [Name],</p><p>Hurry! Our biggest flash sale of the year is on for the next 24 hours. Don't miss out on these exclusive deals.</p><br><a href='#' class='button'>Shop the Sale</a>"
    },
    {
        "name": "12_Educational_Content",
        "title": "How to get the most out of our product",
        "body": "<p>Hi [Name],</p><p>Did you know you can do [Action] with our product? Here's a quick guide to help you master this feature.</p><br><a href='#' class='button'>Read the Guide</a>"
    },
    {
        "name": "13_Milestone_Celebration",
        "title": "Happy Anniversary!",
        "body": "<p>Hi [Name],</p><p>It's been exactly one year since you joined us! To celebrate, here is a special gift just for you.</p><br><a href='#' class='button'>Claim Your Gift</a>"
    },
    {
        "name": "14_Referral_Request",
        "title": "Share the love (and get rewarded)",
        "body": "<p>Hi [Name],</p><p>If you love our product, why not share it with a friend? When they sign up, you both get $20 in credit!</p><br><a href='#' class='button'>Refer a Friend</a>"
    },
    {
        "name": "15_Account_Update",
        "title": "Important changes to your account",
        "body": "<p>Hi [Name],</p><p>We are updating our Terms of Service to better serve you. Please take a moment to review the changes.</p><br><a href='#' class='button'>Review Changes</a>"
    }
]

out_dir = "email_marketing_templates"
os.makedirs(out_dir, exist_ok=True)

for t in templates:
    html_source = boilerplate.format(title=t['title'], body=t['body'])
    file_path = os.path.join(out_dir, f"{t['name']}.html")
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(html_source)
    print(f"Created: {file_path}")

print("Successfully created 15 email templates!")
