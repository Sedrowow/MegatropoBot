from PIL import Image, ImageDraw, ImageFont, ImageOps
import numpy as np
from datetime import datetime
import os
from models import UserPass

class PassGenerator:
    def __init__(self):
        self.font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
        self.width = 400
        self.height = 250
        self.verification_height = 20
        self.colorless_width = 12  # 12 pixels wide
        self.colorless_height = 6  # 6 rows
        self.colored_width = 12    # 12 pixels wide
        self.colored_height = 6    # 6 rows
        self.line_spacing = 4      # Space between colorless and colored parts
        self.grid_size = 2         # Size of each grid cell in pixels

    def create_pass_image(self, user_pass: UserPass, username: str) -> Image.Image:
        img = Image.new('RGB', (self.width, self.height), 'white')
        draw = ImageDraw.Draw(img)

        # Add faction icon if exists
        if user_pass.faction_id:
            faction_icon = Image.open(f"images/faction_{user_pass.faction_id}.png")
            faction_icon = faction_icon.resize((50, 50))
            img.paste(faction_icon, (20, 20))

        # Add nation icon if exists
        if user_pass.nation_id:
            nation_icon = Image.open(f"images/nation_{user_pass.nation_id}.png")
            nation_icon = nation_icon.resize((50, 50))
            img.paste(nation_icon, (self.width - 70, 20))

        # Add user information
        y = 80
        draw.text((20, y), f"User: {username}", fill='black', font=self.font)
        y += 25

        if user_pass.faction_id:
            draw.text((20, y), f"Faction Rank: {user_pass.faction_rank}", fill='black', font=self.font)
            y += 25

        if user_pass.nation_id:
            draw.text((20, y), f"Nation Rank: {user_pass.nation_rank}", fill='black', font=self.font)
            y += 25

        draw.text((20, y), f"Issue Date: {user_pass.issue_date.strftime('%Y-%m-%d')}", fill='black', font=self.font)
        y += 25
        draw.text((20, y), f"Expiry Date: {user_pass.expiry_date.strftime('%Y-%m-%d')}", fill='black', font=self.font)

        # Add verification line with grid pattern
        line_y = self.height - 40  # Move up to accommodate grid
        start_x = (self.width - (self.colorless_width + self.line_spacing + self.colored_width) * self.grid_size) // 2

        # Draw colorless part in 12x6 grid
        colorless = user_pass.pass_identifier.colorless_part
        for x in range(self.colorless_width):
            for y in range(self.colorless_height):
                # Calculate color value based on position in grid
                grid_pos = (y * self.colorless_width + x) % len(colorless)
                color_value = int(colorless[grid_pos], 16) * 16
                # Fill grid cell
                for dx in range(self.grid_size):
                    for dy in range(self.grid_size):
                        draw.point(
                            (start_x + x * self.grid_size + dx, line_y + y * self.grid_size + dy),
                            fill=(color_value, color_value, color_value)
                        )

        # Draw colored part in 12x6 grid
        colored = user_pass.pass_identifier.colored_part
        colored_start_x = start_x + (self.colorless_width * self.grid_size) + self.line_spacing
        for x in range(self.colored_width):
            for y in range(self.colored_height):
                # Calculate color value based on position in grid
                grid_pos = (y * self.colored_width + x) % len(colored)
                color_value = int(colored[grid_pos], 16)
                color = ((color_value & 4) * 64, (color_value & 2) * 64, (color_value & 1) * 64)
                # Fill grid cell
                for dx in range(self.grid_size):
                    for dy in range(self.grid_size):
                        draw.point(
                            (colored_start_x + x * self.grid_size + dx, line_y + y * self.grid_size + dy),
                            fill=color
                        )

        return img

    def extract_verification_line(self, image: Image.Image) -> tuple[str, str]:
        """Extract both parts of the verification line from an image."""
        line_y = self.height - 40
        start_x = (self.width - (self.colorless_width + self.line_spacing + self.colored_width) * self.grid_size) // 2
        
        # Get the verification line region
        line_data = np.array(image)

        # Extract colorless part - sample center of each grid cell
        colorless_values = []
        for y in range(self.colorless_height):
            for x in range(self.colorless_width):
                # Get center pixel of grid cell
                sample_x = start_x + x * self.grid_size + self.grid_size // 2
                sample_y = line_y + y * self.grid_size + self.grid_size // 2
                value = line_data[sample_y][sample_x][0]  # Get grayscale value
                colorless_values.append(format(value // 16, 'x'))

        # Extract colored part - sample center of each grid cell
        colored_values = []
        colored_start_x = start_x + (self.colorless_width * self.grid_size) + self.line_spacing
        for y in range(self.colored_height):
            for x in range(self.colored_width):
                # Get center pixel of grid cell
                sample_x = colored_start_x + x * self.grid_size + self.grid_size // 2
                sample_y = line_y + y * self.grid_size + self.grid_size // 2
                r, g, b = line_data[sample_y][sample_x]
                color_value = ((r > 32) << 2) | ((g > 32) << 1) | (b > 32)
                colored_values.append(format(color_value, 'x'))

        return (''.join(colorless_values[:72]), ''.join(colored_values[:72]))  # 12x6 = 72 pixels total

    def verify_pass_image(self, image_path: str, user_pass: UserPass) -> tuple[bool, list[str], Image.Image]:
        """Verify a pass image and return (is_valid, discrepancies, marked_image)"""
        discrepancies = []
        
        try:
            image = Image.open(image_path)
            if image.size != (self.width, self.height):
                discrepancies.append("Invalid image dimensions")
                return False, discrepancies, image

            # Extract and verify the verification line
            colorless, colored = self.extract_verification_line(image)
            if colorless != user_pass.pass_identifier.colorless_part:
                discrepancies.append("Invalid faction/nation identifier")
            if colored != user_pass.pass_identifier.colored_part:
                discrepancies.append("Invalid user identifier")

            # Create a copy for marking discrepancies
            marked_image = image.copy()
            draw = ImageDraw.Draw(marked_image)

            # Check expiry date
            if datetime.now() > user_pass.expiry_date:
                discrepancies.append("Pass expired")
                draw.text((20, 40), "EXPIRED", fill='red', font=self.font)

            # If there are discrepancies, mark them on the image
            if discrepancies:
                for i, disc in enumerate(discrepancies):
                    draw.text((20, 140 + i*20), disc, fill='red', font=self.font)
                draw.rectangle([(0, 0), (self.width-1, self.height-1)], outline='red', width=3)

            return len(discrepancies) == 0, discrepancies, marked_image

        except Exception as e:
            discrepancies.append(f"Error processing image: {str(e)}")
            return False, discrepancies, Image.new('RGB', (self.width, self.height), 'white')
