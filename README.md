Automatically claim free games from itch.io

## Install
```bash
pip install ItchClaim
```

## Usage

```bash
itchclaim --login <username> claim
```
This command logs in the user (asks for password if it's ran for the first time), refreshes the list of currently free games, and start claiming the unowned ones.

## Advanced Usage

### Logging in (via flags)
If you don't have access to an interactive shell, you can provide you password via flags too.

```bash
itchclaim --login <username> --password <password> --totp <2FA code or secret>
```

### Refresh Library
```bash
itchclaim --login <username> refresh_library
```
Allows you to refresh the locally stored list of owned games. Useful if you have claimed/purchased games since you have started using the script.

### Refresh sale cache

#### Download cached sales from CI (recommended)
```bash
itchclaim refresh_from_remote_cache [--url <url>]
```
ItchClaim collects new sales from itch.io every 6 hours and publishes them on GitHub. Using this method, sales don't need to be scraped by every user, greatly reducing the load on itch.io generated by the script. Also removes expired sales from disk. This command is automatically executed by the `claim` command.

### Download links
```bash
itchclaim [--login <username>] download_urls
```
Generate a download URL for a game. These links have an expiration date. If the game doesn't require claiming, this command can be run without logging in.
*Note: this command is currently broken.*

## CI Commands

*Note: These commands were created for use on the CI, and are not recommended for general users.*

#### Manually collect sales from itch.io
```bash
itchclaim refresh_sale_cache --dir web/data/
```
Request details about every single itch.io, and save the $0 ones to the disk.
The initial run can take 12+ hours.

#### Parameters
- **dir:** Output directory

### Generate static website
```bash
itchclaim generate_web --dir web/data/ --web_dir web/
```
Generates a static HTML file containing a table of all the sales cached on the disk.
This command was created for use on the CI, and is not recommended for general users.

#### Parameters
- **dir:** Location of the data collected about games, as generated by the `refresh_sale_cache` command
- **web_dir:** The output directory

## FAQ

### Is this legal?
This tools is not affiliated with itch.io. Using it may not be allowed, and may result in your account getting suspended or banned. Use at your own risk.

### Can itch.io detect that I'm using this tool?
Yes. We explicitly let itch.io know that use the the requests were sent by this tool, using the `user-agent` header. Itch.io doesn't block using non-browser user agents (like some big corporations do), so I think that they deserve to know how their services are being used. If they want to block ItchClaim, blocking this user-agent makes it simple for them. This way, they won't have to implement additional anti-bot technologies, which would make both our and itch.io's life worse.

### Why sales are not downloaded directly from itch.io?
The initial plan was to parse https://itch.io/games/on-sale on each run (it was even implemented in [here](https://github.com/Smart123s/ItchClaim/blob/00ddfa3dfe57c747f09486fd7791f0e1d57347f3/ItchClaim/DiskManager.py#L31-L49)), however, it turns out that only a handful of sales are listed there.
Luckily for us, details about every sale are published at https://itch.io/s/<id\>, where id is a sequentially incremented number. However, downloading data about every single sale published on itch.io generates a lot of load on their servers. To easen the load generated on itch.io by this tool, I've decide to do this scraping only once, on a remote server, and make the data publicly available.

### Can ItchClaim developers see who has access the sale data?
No, every file on the website is hosted by GitHub via their Pages service, and no data is made available to the developers.
