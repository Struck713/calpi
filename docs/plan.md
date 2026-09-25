# calpi

## Project Overview

calpi is a wall calendar that runs on its own. A Raspberry Pi drives a small touchscreen that shows the month's events, keeps itself up to date from shared online calendars, and is set up and managed entirely from its own screen. Once it's configured, nobody should need to touch a computer to keep it running.

This document covers the goals, features and phases of the project. How each piece is built will be covered in a separate technical details document.

## Goals

- **Readable at a glance.** Anyone walking past can see what's coming up this month.
- **Always current.** Events added on a phone or computer show up on the display without anyone doing anything.
- **Self-contained.** Setup and day-to-day management happen on the device itself. No keyboard, monitor swap or separate computer is needed.
- **Configurable.** Every setting can be changed from within the app, from Wi-Fi to refresh timing to overnight dimming.
- **Smooth.** The display feels responsive and never looks frozen or sluggish, even on modest hardware.
- **Reliable.** It starts by itself when powered on, recovers from network drops and power cuts, and keeps showing the most recent events when it's offline.

## Features

### 1. Monthly Calendar View

- Shows the current month as a grid, with today clearly marked.
- Shows each day's events in the grid, colored by which calendar they come from.
- Lets you move forward and back between months, and returns to the current month on its own after a period of inactivity.
- Offers a way to see the full details of a busy day that doesn't fit in its grid cell.
- Moves to the new day and month on its own at midnight.

### 2. First-Time Setup

When the device starts for the first time, or has nothing configured yet, it walks through a short setup on screen:

1. Connect to a Wi-Fi network.
2. Set the time zone and basic preferences.
3. Sign in to a calendar account (starting with iCloud) and choose which calendars to show.
4. Choose how often to refresh and whether to dim overnight.

Every step can be skipped and finished later from Settings. After setup, the device goes straight to the calendar on every boot.

### 3. Settings

A settings area, reached from the main screen, where everything chosen during setup can be changed at any time:

- **Network:** find nearby Wi-Fi networks, connect, forget saved networks, and see the connection status.
- **Accounts and calendars:** add or remove calendar accounts; show, hide, rename or recolor individual calendars.
- **Syncing:** how often events refresh, plus a button to refresh right now.
- **Display:** brightness, and an optional overnight dim or sleep schedule.
- **Preferences:** time zone, the first day of the week, and 12- or 24-hour time.
- **Status:** when the calendars last synced, and any errors in plain language.

Settings are kept on the device, so they survive restarts and power cuts. Text entry, such as passwords, uses an on-screen keyboard.

### 4. Input

- The finished device uses a **touchscreen**, and every screen is designed for fingers: large tap targets and simple gestures.
- During development, the device is tested on a regular portable monitor without touch, so everything must also work with a mouse and keyboard.

### 5. Performance

- The screen should open quickly after power-on.
- Changing months and opening settings should feel instant.
- Background activity, such as syncing, should never make the display stutter.
- It should run for weeks or months without slowing down or needing a restart.

### 6. Calendar Syncing

- The device pulls events from one or more calendar accounts and refreshes them on the schedule set in Settings.
- **iCloud is supported by signing in to the account.** Apple lets other apps read iCloud calendars with an app-specific password, generated once from the Apple ID account page. The device never sees the main Apple ID password, and the app-specific password can be revoked at any time. A short guide will walk through creating one.
- More providers (such as Google Calendar) and more accounts can be added from Settings, so calendars other than iCloud can be shown whenever they're wanted.
- Account sign-in details are stored securely on the device.
- Events are stored on the device, so the calendar stays visible when there's no internet.
- Sync is **read-only** at first: the device displays events but doesn't create or edit them.

## Phases

| Phase | Focus | Outcome |
|---|---|---|
| **1. Foundation** | Device setup and the monthly view with sample events, tested on the portable monitor | The Pi boots straight into a working calendar screen |
| **2. Syncing** | iCloud account sign-in and scheduled refresh | Real events show up on the display on their own |
| **3. Setup and Settings** | First-time setup, Wi-Fi, accounts, and all configurable options | The device can be set up and managed without a separate computer |
| **4. Touch and Polish** | Move to the touchscreen, tune performance, add overnight dimming and error handling | The device is ready to leave running every day |
| **5. Extras** (optional) | Weather, other views (week or agenda), more providers | Nice-to-haves once the core is solid |

## Decisions

| Topic | Decision |
|---|---|
| Screen | Touchscreen in the finished device; a non-touch portable monitor for testing, so mouse and keyboard must also work |
| iCloud connection | Account sign-in with an app-specific password, which is more secure than a public sharing link |
| Refresh frequency | Configurable in the app |
| Overnight dimming | Configurable in the app, including whether it happens and on what schedule |
| Calendars beyond iCloud | Configurable in the app; accounts and calendars can be added or removed at any time |
| Where things are configured | Inside the app, with a guided first-time setup and a Settings area for later changes, including networking |

## Out of Scope for Now

- Creating or editing events from the device
- Remote management from a phone or web browser
- Supporting several screens or devices
