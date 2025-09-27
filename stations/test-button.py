#!/usr/bin/env python3
import asyncio
import argparse
import RPi.GPIO as GPIO


class ButtonMonitor:
    def __init__(self, pin, invert=False):
        self.pin = pin
        self.invert = invert
        self.last_state = None

        # Setup GPIO
        GPIO.setmode(GPIO.BOARD)
        GPIO.setup(self.pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        print(f"Monitoring physical pin {self.pin}")
        print("Press Ctrl+C to exit")
        if self.invert:
            print("Pin states: HIGH = pressed, LOW = not pressed (inverted logic)")
        else:
            print("Pin states: HIGH = not pressed, LOW = pressed (pull-up logic)")
        print("-" * 60)

    async def monitor(self):
        """Monitor button state and print changes"""
        while True:
            # Read current state
            raw_state = GPIO.input(self.pin)

            # Apply logic based on invert setting
            if self.invert:
                pressed = raw_state  # Direct: HIGH = pressed, LOW = not pressed
            else:
                pressed = not raw_state  # Inverted: LOW = pressed, HIGH = not pressed

            # Check if state changed
            if self.last_state is None or pressed != self.last_state:
                state_text = "PRESSED" if pressed else "RELEASED"
                raw_text = "LOW" if raw_state == 0 else "HIGH"
                print(f"Pin {self.pin}: {state_text} (raw: {raw_text})")
                self.last_state = pressed

            await asyncio.sleep(0.05)  # Check every 50ms

    def cleanup(self):
        """Clean up GPIO resources"""
        GPIO.cleanup()
        print(f"\nGPIO cleanup completed for physical pin {self.pin}")


def parse_arguments():
    parser = argparse.ArgumentParser(description="GPIO Button Monitor Test")
    parser.add_argument(
        "--pin",
        type=int,
        default=18,
        help="Physical pin number to monitor (default: 18)",
    )
    parser.add_argument(
        "--invert",
        action="store_true",
        help="Invert button logic (HIGH=pressed, LOW=released)",
    )
    return parser.parse_args()


async def main():
    args = parse_arguments()

    try:
        monitor = ButtonMonitor(args.pin, args.invert)
        await monitor.monitor()
    except KeyboardInterrupt:
        print("\nStopping button monitor...")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        try:
            monitor.cleanup()
        except:
            pass


if __name__ == "__main__":
    asyncio.run(main())
