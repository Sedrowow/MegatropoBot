from PIL import Image, ImageDraw, ImageFont, ImageOps
import numpy as np
from datetime import datetime
import os
from models import UserPass

class PassGenerator:
    def __init__(self):
        self.font = ImageFont.truetype("arial.ttf", 16)
        self.width = 400
        self.height = 250
        self.verification_height = 20

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

        # Add verification line
        line_y = self.height - 20
        line_width = self.width - 40
        mid_point = line_width // 2

        # Draw colorless part
        for x in range(20, 20 + mid_point):
            color_value = int(user_pass.pass_identifier.colorless_part[((x-20) * 6) // mid_point], 16) * 16
            draw.point((x, line_y), fill=(color_value, color_value, color_value))

        # Draw colored part
        colored = user_pass.pass_identifier.colored_part
        for x in range(20 + mid_point, self.width - 20):
            pos = ((x - (20 + mid_point)) * 6) // mid_point
            if pos < len(colored):
                color_value = int(colored[pos], 16)
                color = ((color_value & 4) * 64, (color_value & 2) * 64, (color_value & 1) * 64)
                draw.point((x, line_y), fill=color)

        return img

    def extract_verification_line(self, image: Image.Image) -> tuple[str, str]:
        """Extract both parts of the verification line from an image."""
        line_y = self.height - 20
        line = np.array(image.getdata()).reshape(self.height, self.width, 3)
        line = line[line_y]

        # Extract colorless part
        mid_point = (self.width - 40) // 2
        colorless_values = []
        for x in range(20, 20 + mid_point):
            # Convert grayscale value back to hex
            value = format(line[x][0] // 16, 'x')
            colorless_values.append(value)

        # Extract colored part
        colored_values = []
        for x in range(20 + mid_point, self.width - 20):
            r, g, b = line[x]
            # Convert RGB values back to our 4-value encoding
            color_value = ((r > 32) << 2) | ((g > 32) << 1) | (b > 32)
            colored_values.append(format(color_value, 'x'))

        return (''.join(colorless_values[:6]), ''.join(colored_values[:6]))

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
