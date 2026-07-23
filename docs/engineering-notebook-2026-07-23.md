# Engineering Notebook — AI Security Robot Data Platform

**Date:** July 23, 2026  
**Project:** AI Security Robot Data Platform  
**Engineer:** Trinity Matthew Ison

## Objective

My goal was to finish the integration layer that collects operational data from
the Sure Sight door-projection system, Ring camera, and Indoor Security Rover.
The platform needed to preserve each project's independent function while
providing one place to review security events and robot telemetry.

## Work completed

I expanded the Flask platform running on the Jetson Orin Nano to collect three
different types of real-time data.

First, I added a Ring camera collector. The collector authenticates with a
locally stored token and polls the Front Door camera for motion and on-demand
events. It records the Ring event ID, event type, timestamp, answered state,
device name, Wi-Fi signal, battery value when available, and the latest
snapshot. The token and image remain in the ignored runtime directory.

Next, I connected the Sure Sight runtime through its local `/api/status`
endpoint. The data platform now polls the alert state, event ID, message,
projector state, and remaining alert time. When the event ID changes, the
platform writes a `sure_sight_alert` record to the same event log used by the
other systems.

I retained the rover telemetry pipeline and verified its rolling five-sample
median filter. The filter reduces noise in the ultrasonic readings before the
platform classifies the environment as `CLEAR`, `CAUTION`, or `OBSTACLE`.
Proximity-state changes are stored as rover events.

Finally, I changed the combined event API so it reads from the persistent JSON
Lines file after a restart. I also normalized older proximity records that were
created before the `source` field was added, allowing them to appear correctly
as rover data.

## Problems and solutions

### Port 5050 was already in use

An older background instance of the Flask platform was still running. I used
the listening-port information to identify the exact Python process, verified
its command line, and terminated it before starting the updated version.

### Transfer command was run on the wrong system

A Windows PowerShell `scp` command was initially entered in the Jetson terminal.
The Windows path could not exist on Linux. I corrected the workflow by running
`scp` from Windows and transferring each integration package to
`/home/trinity/` on the Jetson.

### Ring events initially lacked a snapshot

The Ring connection and event history worked first. After the service restarted
and completed another polling cycle, the snapshot endpoint reported that an
image was available.

### Historical rover records showed an unknown source

Older proximity records did not contain a `source` field. I updated the current
analytics logger to write `source: rover` and added compatibility handling that
classifies previous `proximity_state_change` records as rover events when they
are read.

## Verification

The completed system produced the following verified results:

- Ring collector connected to the `Front Door` device.
- Ring Wi-Fi health reported a good signal.
- Ring motion and on-demand events were collected.
- Sure Sight status collector connected to port 5000.
- Sure Sight alert event `3` was captured while active.
- The alert message and projector state were recorded.
- The persistent API recovered 61 event records after restarting the platform.
- The final timeline identified Ring, Sure Sight, and rover sources.
- All modified Python files passed compilation.

## Engineering significance

This project demonstrates real-time embedded-system integration because the
Jetson receives asynchronous data from cameras, a projection runtime, and a
mobile robot while maintaining responsive controls and local event storage. It
also demonstrates signal processing through median filtering of ultrasonic
measurements and high-speed digital communication through Wi-Fi camera streams,
HTTP APIs, and the rover's TCP bridge.

The strongest result is that the projects are no longer isolated
demonstrations. They now operate as parts of one security ecosystem while
remaining modular enough to test, replace, or improve independently.

## Next steps

The functional platform is complete. My next changes will focus on improving
the dashboard's appearance and presentation without changing the verified data
collection architecture.
