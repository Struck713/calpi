# Security: credential storage

## What is stored, and where
- `<state>/credentials.bin`: all account secrets (app-specific passwords), one AES-256-GCM encrypted file (mode 0600). Account ids are inside the encrypted part too.
- `<state>/keys/credentials.key` (dir 0700, file 0600): 32 random bytes, created on first use, never overwritten.
- The encryption key is HKDF-SHA256 over the key file, salted with the SHA-256 of the Pi's hardware serial number (the serial is not stored on the SD card).
- Account records without secrets (username, server) live in `settings.json`. Wi-Fi passwords are stored by NetworkManager.

## Protected against
- Reading a lost, stolen or copied SD card / disk image on another computer: without this Pi's serial the file cannot be decrypted.
- Accidental exposure: secrets are never in settings, logs (a redacting filter and formatter replace known secret values with `***`, including in tracebacks), `repr()`, or command lines.

## Not protected against
- Anyone with root or physical access to the running Pi: they can read both the key file and the serial. A Pi 3B has no TPM or secure element, and a kiosk has no login password to unlock a keyring, so this cannot be prevented.
- Secrets exist in process memory while in use (Python strings cannot be wiped).

## Moved SD card or changed hardware
The store becomes "unreadable": the app keeps running, logs one error, and asks for the accounts to be signed in again. Signing in again moves the old file aside as `credentials.bin.unreadable-<timestamp>` and starts a fresh store.

## If the device is lost
Revoke the app-specific password at account.apple.com: Sign-In and Security, App-Specific Passwords.
