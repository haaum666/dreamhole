# Privacy Policy — DreamHole

Last updated: April 2026

## What DreamHole does

DreamHole is a browser extension that provides analytics for job listings on hh.ru. It shows salary comparisons, vacancy history, company hiring trends, and anonymous interview reviews.

## Data we collect

### Anonymous identifier

The extension generates a random UUID stored locally on your device via chrome.storage.local. This UUID is used solely to:

- Prevent duplicate reviews (one review per user per company)
- Prevent duplicate votes on reviews

The UUID is hashed with SHA-256 before being sent to the server. We cannot identify you from this hash.

### Reviews

When you voluntarily submit an interview review, the following data is sent to our server:

- Company ID and name (from hh.ru)
- Your review content (stages, ratings, comments)
- Anonymous user hash

No personal information (name, email, IP address) is collected or stored.

### Browsing data

The extension reads the URL of the current tab **only** to detect if you are viewing a vacancy on hh.ru and extract the vacancy ID. URLs are not stored or transmitted.

## Data we do NOT collect

- Names, emails, or any personally identifiable information
- Browsing history
- Passwords or authentication data
- Financial information
- Location data
- Keystrokes or mouse movements

## Third-party services

The extension communicates with:

- **hh.ru** (read-only, to display vacancy data on the page)
- **moiraidrone.fvds.ru** (our own backend server, to fetch analytics and store reviews)

No data is sold or shared with third parties.

## Data retention

Reviews are stored indefinitely to provide value to other users. Local data (UUID) can be deleted by uninstalling the extension.

## Contact

If you have questions about this privacy policy, please open an issue at [github.com/haaum666/dreamhole](https://github.com/haaum666/dreamhole/issues).
