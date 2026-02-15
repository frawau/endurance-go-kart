#!/usr/bin/env python3
import os
import mmap
import struct
import time
from PIL import Image, ImageDraw, ImageFont


class FramebufferDisplay:
    def __init__(self):
        self.fb_device = "/dev/fb0"
        self.get_screen_info()

        try:
            self.fb_fd = os.open(self.fb_device, os.O_RDWR)
            self.fb_map = mmap.mmap(self.fb_fd, self.screen_size)
            print(f"Framebuffer opened successfully: {self.width}x{self.height}")
        except Exception as e:
            print(f"Error opening framebuffer: {e}")
            print("Make sure you're running as root or have proper permissions")
            raise

        # Load font
        try:
            self.large_font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 200
            )
            self.medium_font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 100
            )
            print("Fonts loaded successfully")
        except Exception as e:
            print(f"Font loading failed, using default: {e}")
            self.large_font = ImageFont.load_default()
            self.medium_font = ImageFont.load_default()

    def get_screen_info(self):
        # For RPi Zero W with bookworm, let's use common resolutions
        # Try to detect from /sys/class/graphics/fb0/virtual_size first
        try:
            with open("/sys/class/graphics/fb0/virtual_size", "r") as f:
                size_str = f.read().strip()
                width, height = map(int, size_str.split(","))
                self.width = width
                self.height = height
                print(
                    f"Detected framebuffer size from sysfs: {self.width}x{self.height}"
                )
        except Exception as e:
            print(f"Sysfs detection failed ({e}), using fallback resolution")
            # Fallback to common resolution
            self.width = 1920
            self.height = 1080

        self.bpp = 32  # 32 bits per pixel (RGBA)
        self.screen_size = self.width * self.height * (self.bpp // 8)
        print(
            f"Screen setup: {self.width}x{self.height}, {self.bpp}bpp, {self.screen_size} bytes"
        )

    def fill_screen(self, color):
        """Fill entire screen with a solid color"""
        try:
            # Pack color as BGRA (framebuffer format)
            pixel = struct.pack("BBBB", color[2], color[1], color[0], 255)
            data = pixel * (self.width * self.height)
            self.fb_map.seek(0)
            self.fb_map.write(data)
            self.fb_map.flush()
            print(f"Screen filled with color {color}")
        except Exception as e:
            print(f"Error filling screen: {e}")

    def display_text(self, text, bg_color, text_color, font=None):
        """Display text centered on screen"""
        try:
            if font is None:
                font = self.large_font

            # Create image
            img = Image.new("RGB", (self.width, self.height), bg_color)
            draw = ImageDraw.Draw(img)

            # Calculate text position (centered)
            bbox = draw.textbbox((0, 0), text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            x = (self.width - text_width) // 2
            y = (self.height - text_height) // 2

            # Draw text
            draw.text((x, y), text, fill=text_color, font=font)

            # Display image
            self.display_image(img)
            print(f"Displayed text: '{text}'")

        except Exception as e:
            print(f"Error displaying text: {e}")

    def display_image(self, img):
        """Display PIL image on framebuffer"""
        try:
            # Resize if necessary
            if img.size != (self.width, self.height):
                img = img.resize((self.width, self.height))

            # Convert RGB to BGRA more efficiently
            # Convert to numpy array for faster processing
            try:
                import numpy as np

                # Convert PIL image to numpy array
                rgb_array = np.array(img)

                # Create BGRA array
                bgra_array = np.zeros((self.height, self.width, 4), dtype=np.uint8)
                bgra_array[:, :, 0] = rgb_array[:, :, 2]  # B
                bgra_array[:, :, 1] = rgb_array[:, :, 1]  # G
                bgra_array[:, :, 2] = rgb_array[:, :, 0]  # R
                bgra_array[:, :, 3] = 255  # A

                data = bgra_array.tobytes()

            except ImportError:
                # Fallback: use PIL's built-in conversion (slower but works)
                print("NumPy not available, using slower conversion...")

                # Convert to RGBA first, then swap channels
                if img.mode != "RGBA":
                    img = img.convert("RGBA")

                # Get raw pixel data
                pixels = img.tobytes()

                # Convert RGBA to BGRA
                data = b""
                for i in range(0, len(pixels), 4):
                    r, g, b, a = pixels[i : i + 4]
                    data += struct.pack("BBBB", b, g, r, 255)

            # Write to framebuffer
            self.fb_map.seek(0)
            self.fb_map.write(data)
            self.fb_map.flush()

        except Exception as e:
            print(f"Error displaying image: {e}")

    def close(self):
        """Clean up resources"""
        try:
            if hasattr(self, "fb_map"):
                self.fb_map.close()
            if hasattr(self, "fb_fd"):
                os.close(self.fb_fd)
            print("Framebuffer closed")
        except Exception as e:
            print(f"Error closing framebuffer: {e}")


def main():
    print("RPi Zero W Framebuffer Display Test")
    print("====================================")

    try:
        display = FramebufferDisplay()

        # Test sequence
        tests = [
            ("Red screen", (255, 0, 0)),
            ("Green screen", (0, 255, 0)),
            ("Black screen", (0, 0, 0)),
            ("Blue screen", (0, 0, 255)),
            ("White screen", (255, 255, 255)),
        ]

        for test_name, color in tests:
            print(f"\nTest: {test_name}")
            display.fill_screen(color)
            time.sleep(2)

        # Test text display with more debugging
        print("\nTest: Text display")
        print("About to display 'HELLO'...")
        try:
            display.display_text(
                "HELLO", (255, 165, 0), (0, 0, 0)
            )  # Orange background, black text
            print("HELLO displayed, waiting 3 seconds...")
            time.sleep(3)

            print("About to display 'RPi ZERO W'...")
            display.display_text(
                "RPi ZERO W", (0, 255, 0), (255, 255, 255)
            )  # Green background, white text
            print("RPi ZERO W displayed, waiting 3 seconds...")
            time.sleep(3)

            print("About to display '123'...")
            display.display_text(
                "123", (255, 0, 0), (255, 255, 0)
            )  # Red background, yellow text
            print("123 displayed, waiting 3 seconds...")
            time.sleep(3)
        except Exception as e:
            print(f"Text display error: {e}")
            import traceback

            traceback.print_exc()

        # Test countdown simulation
        print("\nTest: Countdown simulation")
        for i in range(5, 0, -1):
            display.display_text(str(i), (255, 165, 0), (0, 0, 0))
            time.sleep(1)

        # Final green screen
        display.fill_screen((0, 255, 0))
        print("\nTest completed! Green screen should be visible.")
        time.sleep(3)

        # Return to black
        display.fill_screen((0, 0, 0))

    except Exception as e:
        print(f"Test failed: {e}")
        return 1

    finally:
        try:
            display.close()
        except:
            pass

    print("\nAll tests completed successfully!")
    return 0


if __name__ == "__main__":
    exit(main())
