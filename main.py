import logging
import time
from datetime import time as dt_time
from datetime import datetime
import feedparser
from telegram.ext import CommandHandler, CallbackContext, Updater
from newspaper import Article
from openai import OpenAI
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import re
from collections import defaultdict, Counter

# Set up logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Load your bot token and channel ID from a configuration file or environment variables
BOT_TOKEN = 'ENTER YOUR BOT TOKEN HERE'
DAILY_CHANNEL = '@CHANNEL_ID' #Hourly updates
DAILY_SUMMARY = '@CHANNEL_ID' #Daily updates

# File to store the subscribed RSS feeds
RSS_FILE = 'articlexml.txt'

# List to store subscribed RSS feeds
rss_feeds = []

# List to store daily RSS Links
daily_links = []


def load_rss_feeds():
    #Load the subscribed RSS feeds from the file
    try:
        with open(RSS_FILE, 'r') as file:
            rss_feeds.extend(file.read().splitlines())
    except FileNotFoundError:
        pass


def load_daily_links():
    global daily_links

    try:
        
        # Set up Google Sheets API credentials
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        credentials = ServiceAccountCredentials.from_json_keyfile_name('client_key.json', scope)
        gc = gspread.authorize(credentials)
        
        # Open the Google Sheet using its name
        sheet = gc.open('YOUR-SHEETNAME').worksheet('Sheet1')  # Assuming the sheet is the first sheet (Sheet1)
        # Get all values in the worksheet
        rows = sheet.get_all_values()[1:]
        today_date = datetime.today().strftime('%m/%d/%Y')

        # Filter rows for today's date and load links into daily_links
        daily_links = [row[2] for row in rows if row[0] == today_date]
        print("Daily links loaded successfully.")

    except Exception as e:
        print(f"Failed to load daily links: {e}")
    

def save_rss_feeds():
    #Save the subscribed RSS feeds to the file
    with open(RSS_FILE, 'w') as file:
        for rss_url in rss_feeds:
            file.write(f'{rss_url}\n')


def start(update, context):
    #Send a welcome message when the command /start is issued
    update.message.reply_text('Welcome! Use /addrss <rss_url> to subscribe to an RSS feed.')


def add_rss(update, context):
    #Add an RSS feed to the subscription list
    if len(context.args) == 0:
        update.message.reply_text('Please provide an RSS URL to subscribe.')
        return

    rss_url = context.args[0]
    rss_feeds.append(rss_url)
    save_rss_feeds()  # Save the updated feeds to the file
    update.message.reply_text(f'Subscribed to RSS feed: {rss_url}')


def remove_rss(update, context):
    #Remove an RSS feed from the subscription list
    if len(context.args) == 0:
        update.message.reply_text('Please provide an RSS URL to unsubscribe.')
        return

    rss_url = context.args[0]
    if rss_url in rss_feeds:
        rss_feeds.remove(rss_url)
        save_rss_feeds()  # Save the updated feeds to the file
        update.message.reply_text(f'Unsubscribed from RSS feed: {rss_url}')
    else:
        update.message.reply_text('This RSS feed is not in the subscription list.')


def summarise_by_content(prompt):
    get_summary = ''
    client = OpenAI(
        api_key='YOUR-OPENAI-KEY'
    )
    while not get_summary:
        response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": prompt}         
                    ],
                temperature=0.7,
                max_tokens=200,
                n=1,
                stop=None
            )
        get_summary = response.choices[0].message.content
        if "as an AI text-based assistant" in get_summary or "as an AI text-based model" in get_summary or "as an AI language model" in get_summary:
            get_summary = ''
        else:
            return get_summary

 
def summarise_by_url(prompt):
    client = OpenAI(
        #update to use your own api_key from openai
        api_key='YOUR-OPENAI-KEY'
    )
    while not get_summary:
        response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": prompt}                
                    ],
                temperature=0.7,
                max_tokens=200,
                n=1,
                stop=None
            )
        get_summary = response.choices[0].message.content
        if "as an AI text-based assistant" in get_summary or "as an AI text-based model" in get_summary or "as an AI language model" in get_summary:
            get_summary = ''
        else:
            return get_summary


def data_to_string(data):
    headers = data[0]  # Extracting the header
    body = data[1:]  # The rest of the data
    
    # Initialize an empty string to append data descriptions
    description = ""
    
    for row in body:
        # Combine each header with its corresponding value in the row
        # and format it into a readable sentence.
        row_description = ". ".join([f"{header}: {value}" for header, value in zip(headers, row)])
        description += row_description + "\n\n"
    
    return description

# Get the descriptive text

    
def fetch_and_send_rss_summaries(bot, chat_id):
    """Summarize and send the latest articles from subscribed RSS feeds to the broadcast channel."""
    try:
        for rss_url in rss_feeds:
            feed = feedparser.parse(rss_url)
            for entry in feed.entries:
                article = Article(entry.link, language='en')
                article.download()
                article.parse()
                title = entry.title
                link = entry.link
                prompt = f"Given the attached article, perform the following tasks: Provide keywords related to the industry discussed in the article(Reply with Keywords: (keywords) and keep it short). Identify and list names of famous Singaporeans mentioned (Reply with Singaporeans: (singaporeans)). Identify and name famous companies (Reply with Companies: (companies)). Determine which category of PESTEL the news article predominantly falls into(Reply with ONE CATEGORY ONLY without explanations. PESTEL: (pastel)). Offer insights into any discernible trends or emerging themes within the article(150 words or less and reply with Insights:).\n {article.text}"
                summary = generate_summary(link,prompt)

                if summary != "link exists":
                    # Save the summary to Google Sheet
                    print(summary)
                    daily_links.append(link)
                    summary_message = f"<b>{title}</b>\n{link}\n{summary}"
                    bot.send_message(chat_id=chat_id, text=summary_message, parse_mode="HTML")
                    save_to_google_sheet(title, link, summary)
                else:
                    continue
                time.sleep(5)

    except Exception as e:
        error_message = f"An error has occurred: {e}"
        bot.send_message(chat_id=chat_id,text=error_message)


def run_summarise_rss(update, context):
    fetch_and_send_rss_summaries(context.bot, DAILY_CHANNEL)


def scheduled_summarise_rss(context: CallbackContext):
    fetch_and_send_rss_summaries(context.bot, DAILY_CHANNEL)


def generate_summary(link, prompt):
    try:
        if link in daily_links:
            print("link already exists")
            return "link exists"
        else:
            if len(prompt)/4 > 4097:
                prompt = f"Given the attached article, perform the following tasks: Provide keywords related to the industry discussed in the article(Reply with Keywords: (keywords) and keep it short). Identify and list names of famous Singaporeans mentioned (Reply with Singaporeans: (singaporeans)). Identify and name famous companies (Reply with Companies: (companies)). Determine which category of PESTEL the news article predominantly falls into(Reply with ONE CATEGORY ONLY without explanations. PESTEL: (pastel)). Offer insights into any discernible trends or emerging themes within the article(150 words or less and reply with Insights:).\n {link}"
                return summarise_by_url(prompt)
            else:
                return summarise_by_content(prompt)
            
    except Exception as e:
        print(f"Failed to generate summary: {e}")
        return "Failed to generate summary."
    

def save_to_google_sheet(title, link, summary):
    # Define patterns for extracting information
    keyword_pattern = r'Keywords:\s*(.*?)\n'
    singaporeans_pattern = r'Singaporeans:\s*(.*?)\n'
    companies_pattern = r'Companies:\s*(.*?)\n'
    pestel_pattern = r'PESTEL:\s*(.*?)\n'
    insights_pattern = r'Insights:\s*(.*?)$'
    
    def remove_trailing_period(s):
        return s[:-1] if s.endswith('.') else s
    
    def extract_with_pattern(pattern, text):
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            return remove_trailing_period(match.group(1).strip().replace(', ', '\n'))
        else:
            return None
        
    # Extract information using regular expressions
    keywords = extract_with_pattern(keyword_pattern, summary)
    singaporeans = extract_with_pattern(singaporeans_pattern, summary)
    companies = extract_with_pattern(companies_pattern, summary)
    pestel = extract_with_pattern(pestel_pattern, summary)
    insights = extract_with_pattern(insights_pattern, summary)
    date = datetime.today().strftime('%m/%d/%Y')
    try:
        scope = [
            'https://spreadsheets.google.com/feeds', 
            'https://www.googleapis.com/auth/drive', 
            'https://www.googleapis.com/auth/drive.file'
            ]
        credentials = ServiceAccountCredentials.from_json_keyfile_name('client_key.json', scope)
        gc = gspread.authorize(credentials)
        # Open the Google Sheet using its key
        sheet = gc.open('YOUR-SHEETNAME').worksheet("Sheet1")
        
        #Assign Pestel Category accordingly to importance
        if "None" in pestel or "N/A" in pestel or "None" in pestel or "Not" in pestel or "none" in pestel:
            pestel = "Not categorised"
        elif "Political" in pestel:
            pestel = "Political"
        elif "Economic" in pestel:
            pestel = "Economic"
        elif "Technological" in pestel or "Technology" in pestel:
            pestel = "Technological"
        elif "Legal" in pestel:
            pestel = "Legal"
        elif "Social" in pestel:
            pestel = "Social"
        elif "Environment" in pestel or "Environmental" in pestel:
            pestel = "Environmental"
        # Append the summary to the Google Sheet
        sheet.append_row([date,title, link, keywords, singaporeans, companies, pestel, insights])
        print("Summary saved to Google Sheet successfully.") 

    except Exception as e:
        print(f"Failed to save summary to Google Sheet: {e}")


def send_collated_summary(context: CallbackContext):
    global daily_links

    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        credentials = ServiceAccountCredentials.from_json_keyfile_name('client_key.json', scope)
        gc = gspread.authorize(credentials)
        
        # Open the Google Sheet using its key
        sheet = gc.open('YOUR-SHEETNAME').worksheet("Sheet1")

        # Get all rows in the worksheet
        rows = sheet.get_all_values()[1:]
        VALID_PESTEL_CATEGORIES = {"Political", "Economic", "Social", "Technological", "Environmental", "Legal"}
        # Organize data by PESTEL category
        pestel_links = defaultdict(list)
        date = datetime.today().strftime('%m/%d/%Y')
        for row in rows:
            if len(row) >= 7 and row[0] == date and row[3] and row[6] in VALID_PESTEL_CATEGORIES:  # Ensure the row has at least 7 columns and the third column (link) is not empty
                pestel_category = row[6]  # PESTEL category in the 7th column (0-indexed)
                link = f'<a href="{row[2]}">{row[1]}</a>'
                pestel_links[pestel_category].append(link)  # Add the link to the category list

        # Prepare the collated message
        full_message = f"<b>{date} Summarised</b> \n"
        filtered_data = [row for row in rows if row[0]==date]
        for category, links in pestel_links.items():
            numbered_links = [f"{i+1}. {link}" for i, link in enumerate(links)]
            message_section = f"\n{category}:\n" + '\n'.join(numbered_links) + "\n"
            category_keywords = '\n'.join(row[3] for row in filtered_data if row[6].capitalize() == category)
            most_common_keywords = Counter(category_keywords.split('\n')).most_common(3)
            if most_common_keywords:
                    message_section += f"\nTop 3 Keywords for {category}:\n"
                    for idx, (keyword, count) in enumerate(most_common_keywords, start=1):
                        message_section += f"{idx}. {keyword} ({count} occurrences)\n"
            full_message += message_section
        
        all_keywords = '\n'.join(row[3] for row in filtered_data)
        most_common_keywords = Counter(all_keywords.split('\n')).most_common(5)
        if most_common_keywords:
            full_message += f"\nTop 5 Keywords{' for ' + date }:\n"
            for idx, (keyword, count) in enumerate(most_common_keywords, start=1):
                full_message += f"{idx}. {keyword} ({count} occurrences)\n"
        

        # Function to safely split the message without breaking HTML tags
        def safe_split(text, max_length):
            while text:
                if len(text) <= max_length:
                    yield text
                    break
                else:
                    split_index = text.rfind('\n', 0, max_length)
                    if split_index == -1:
                        split_index = max_length
                    yield text[:split_index]
                    text = text[split_index:]

        full_message += f"\n\nEnd of Summary for {date}"
        #Split the message if it exceeds the Telegram limit and send
        MAX_MESSAGE_LENGTH = 4096
        for part in safe_split(full_message, MAX_MESSAGE_LENGTH):
            context.bot.send_message(chat_id=DAILY_SUMMARY, text=part, parse_mode="HTML", disable_web_page_preview = True)
            time.sleep(1)

        #Keep most recent 60 links
        if len(daily_links) > 60:
            # Keep only the most recent 30 links
            daily_links[:] = daily_links[-60:]
            print(len(daily_links))
            print(daily_links)
    except Exception as e:
        print(f"Failed to send collated summary: {e}")


def overall(update, context):
    try:
        # Parse the command arguments
        args = context.args
        # Define default values
        date_str = None
        category = None
        message = ""

        if len(args) == 0:
            #/overall: Overall stats
            date_str = "all"
        elif len(args) >= 1:
            #/overall 0124: Stats for a specific month and year
            date_str = args[0]
            month_yr = datetime.strptime(date_str, "%m%y")
            month_yr_formatted = month_yr.strftime("%b %Y")
            if len(args) == 2:
                #/overall 0124 category: Stats for a specific month, year, and category
                category = args[1].capitalize()
        
        date_format = "%m%y"
        sheets_date_format = "%m/%d/%Y"
        # Convert the input category to uppercase
        category = category.capitalize() if category else None

        if date_str != "all":
            try:
                #Check if the date is a valid month and year
                datetime.strptime(date_str, date_format).replace(day=1)
            except ValueError:
                update.message.reply_text("Please provide a valid month and year in the format MMYY.")
                return

        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        credentials = ServiceAccountCredentials.from_json_keyfile_name('client_key.json', scope)
        gc = gspread.authorize(credentials)
        sheet = gc.open('YOUR-SHEETNAME').worksheet("Sheet1")
        filtered_data = []

        # Get all rows in the worksheet
        rows = sheet.get_all_values()[1:]  # Skip the first row (titles)

        # Filter data by the provided month, year, and category
        if date_str != "all":
            filtered_data = [row for row in rows if datetime.strptime(row[0], sheets_date_format).strftime("%m%y") == date_str]
        else:
            filtered_data = rows

        # Format message
        if not filtered_data:
            update.message.reply_text(f"No data available for {date_str}.")
            return
        
        if date_str == "all":
            message = "Overall category counts:\n"
            category_counts = Counter(row[6] for row in filtered_data if len(row) > 6)
            sorted_category_counts = sorted(category_counts.items(), key=lambda x: x[1], reverse=True)
            message = f"Category counts for {date_str}:\n"
            for cat, count in sorted_category_counts:
                message += f"{cat}: {count}\n\n"

            # Find the most common keywords within all data
            all_keywords = '\n'.join(row[3] for row in filtered_data)
            most_common_keywords = Counter(all_keywords.split('\n')).most_common(5)

            if most_common_keywords:
                message += f"\nTop 5 Keywords{' for ' + date_str + ' time'}:\n"
                for idx, (keyword, count) in enumerate(most_common_keywords, start=1):
                    message += f"{idx}. {keyword} ({count} occurrences)\n"
        else:
            if category:
                # If a specific category is provided, count the number of entries in that category
                count_in_category = sum(1 for row in filtered_data if row[6].capitalize() == category)
                message = f"PESTEL Category - {category} for {month_yr_formatted}:\nNumber of entries in this category: {count_in_category}\n"

                # Find the most common keywords within the specified category
                category_keywords = '\n'.join(row[3] for row in filtered_data if row[6].capitalize() == category)
                most_common_keywords = Counter(category_keywords.split('\n')).most_common(3)

                if most_common_keywords:
                    message += f"\nTop 3 Keywords:\n"
                    for idx, (keyword, count) in enumerate(most_common_keywords, start=1):
                        message += f"{idx}. {keyword} ({count} occurrences)\n"

            else:
                # If no specific category is provided, show counts for each category ordered by count
                category_counts = Counter(row[6] for row in filtered_data if len(row) > 6)
                sorted_category_counts = sorted(category_counts.items(), key=lambda x: x[1], reverse=True)
                message = f"PESTEL Category counts for {month_yr_formatted}:\n"
                for cat, count in sorted_category_counts:
                    message += f"{cat}: {count}\n"
                
                # Find the most common keywords across all entries for the specified month
                all_keywords = '\n'.join(row[3] for row in rows if datetime.strptime(row[0], sheets_date_format).strftime("%m%y") == date_str)
                most_common_keywords = Counter(all_keywords.split('\n')).most_common(3)

                if most_common_keywords:
                    message += f"\nTop 3 Keywords for {date_str}:\n"
                    for idx, (keyword, count) in enumerate(most_common_keywords, start=1):
                        message += f"{idx}. {keyword} ({count} occurrences)\n\n"

        # Function to safely split the message without breaking HTML tags
        def safe_split(text, max_length):
            while text:
                if len(text) <= max_length:
                    yield text
                    break
                else:
                    split_index = text.rfind('\n', 0, max_length)
                    if split_index == -1:
                        split_index = max_length
                    yield text[:split_index]
                    text = text[split_index:]
        
        MAX_MESSAGE_LENGTH = 4096
        for part in safe_split(message, MAX_MESSAGE_LENGTH):
            context.bot.send_message(chat_id=DAILY_CHANNEL, text=part, parse_mode="HTML", disable_web_page_preview = True)


    except Exception as e:
        update.message.reply_text(f"Failed to retrieve overall data: {e}")


def main():
    """Run the bot."""
    load_rss_feeds()  #Load the subscribed feeds from the file
    load_daily_links() #Load links from google sheets in accordance to today's link when restarting file
    updater = Updater(BOT_TOKEN)
    dp = updater.dispatcher
    
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("addrss", add_rss, pass_args=True))
    dp.add_handler(CommandHandler("removerss", remove_rss, pass_args=True))
    dp.add_handler(CommandHandler("run", run_summarise_rss))
    dp.add_handler(CommandHandler("overall",overall))

    #Schedule the summarize_rss function to run every hour
    updater.job_queue.run_repeating(scheduled_summarise_rss, interval=3600, first=1)


    daily_job_time = dt_time(hour=15, minute=55)  #11:55PM in 24-hour format to sg time
    updater.job_queue.run_daily(send_collated_summary, time=daily_job_time, days=(0, 1, 2, 3, 4, 5, 6))  # Run every day

    updater.start_polling()

    updater.idle()


if __name__ == '__main__':
    main()
