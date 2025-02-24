import random
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
        self.grid_chars = 72  # 12x6 grid = 72 characters
        self.default_pattern = self._generate_checker_pattern()

    def _generate_checker_pattern(self) -> str:
        """Generate a checker pattern for empty faction slots"""
        pattern = ""
        for i in range(self.grid_chars):
            row = (i // 12) % 2  # Alternate by row
            col = (i % 12) % 2   # Alternate by column
            if row == col:
                pattern += "8"  # Dark grey
            else:
                pattern += "4"  # Light grey
        return pattern

    def _generate_user_code(self, user_id: int) -> str:
        """Generate a unique 72-character colored code for a user"""
        import hashlib
        # Create a hash from user ID
        hash_input = f"user_{user_id}_{datetime.now().strftime('%Y%m')}"  # Changes monthly
        hash_obj = hashlib.sha256(hash_input.encode())
        # Convert hash to hex and expand to 72 chars
        hex_hash = hash_obj.hexdigest()
        return (hex_hash * 3)[:72]  # Repeat hash to reach 72 chars

    def _generate_entity_code(self, entity_type: str, entity_id: int) -> str:
        """Generate a unique 72-character code for a faction or nation"""
        import hashlib
        hash_input = f"{entity_type}_{entity_id}"
        hash_obj = hashlib.sha256(hash_input.encode())
        return (hash_obj.hexdigest() * 3)[:72]

    def create_pass_image(self, user_pass: UserPass, username: str) -> Image.Image:
        img = Image.new('RGB', (self.width, self.height), 'white')
        draw = ImageDraw.Draw(img)

        # Add faction icon if exists
        if user_pass.faction_id:
            try:
                faction_icon = Image.open(f"images/faction_{user_pass.faction_id}.png")
            except FileNotFoundError:
                faction_icon = self._generate_default_icon("F")
            faction_icon = faction_icon.resize((50, 50))
            img.paste(faction_icon, (20, 20))

        # Add nation icon if exists
        if user_pass.nation_id:
            try:
                nation_icon = Image.open(f"images/nation_{user_pass.nation_id}.png")
            except FileNotFoundError:
                nation_icon = self._generate_default_icon("N")
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

        # Generate verification codes
        if user_pass.nation_id:
            nation_code = self._generate_entity_code("nation", user_pass.nation_id)
            colorless = nation_code
            if not user_pass.faction_id:
                # Add checker pattern with white trim if needed
                if any(int(nation_code[-1], 16) > 7):
                    colorless = nation_code[:-1] + "0"  # White trim at end
                if any(int(nation_code[0], 16) > 7):
                    colorless = "0" + nation_code[1:]  # White trim at start
        else:
            colorless = self.default_pattern

        if user_pass.faction_id:
            faction_code = self._generate_entity_code("faction", user_pass.faction_id)
            colorless = faction_code
            if user_pass.nation_id:
                # Combine faction and nation codes
                for i in range(72):
                    if i < 36:  # First half faction
                        colorless = faction_code
                    else:  # Second half nation
                        colorless = nation_code

        # Generate colored part (user-specific)
        colored = self._generate_user_code(user_pass.user_id)

        # Draw verification line
        line_y = self.height - 40
        start_x = (self.width - (self.colorless_width * self.grid_size)) // 2

        # Ensure patterns are exactly 72 characters
        colorless = user_pass.pass_identifier.colorless_part[:72].ljust(72, '0')
        colored = user_pass.pass_identifier.colored_part[:72].ljust(72, '0')

        # Draw colorless part
        for i in range(72):
            x = i % 12
            y = i // 12
            color_value = int(colorless[i], 16) * 16
            
            for dx in range(self.grid_size):
                for dy in range(self.grid_size):
                    draw.point(
                        (start_x + x * self.grid_size + dx, line_y + y * self.grid_size + dy),
                        fill=(color_value, color_value, color_value)
                    )

        # Draw colored part
        colored_start_x = start_x + (self.colorless_width * self.grid_size) + self.line_spacing
        for i in range(72):
            x = i % 12
            y = i // 12
            color_val = int(colored[i], 16)
            r = (color_val & 0xF) * 16
            g = (color_val & 0xF) * 16
            b = 0  # Keep blue at 0 for consistent verification
            
            for dx in range(self.grid_size):
                for dy in range(self.grid_size):
                    draw.point(
                        (colored_start_x + x * self.grid_size + dx, line_y + y * self.grid_size + dy),
                        fill=(r, g, b)
                    )

        return img

    def extract_verification_line(self, image: Image.Image) -> tuple[str, str]:
        """Extract both parts of the verification line from an image."""
        line_y = self.height - 40
        start_x = (self.width - (self.colorless_width * self.grid_size)) // 2
        
        line_data = np.array(image)
        colorless_values = []
        colored_values = []

        # Extract both parts
        for i in range(72):
            x = i % 12
            y = i // 12

            # Sample colorless grid
            sample_x = start_x + x * self.grid_size + self.grid_size // 2
            sample_y = line_y + y * self.grid_size + self.grid_size // 2
            gray_value = line_data[sample_y][sample_x][0]
            colorless_values.append(format(gray_value // 16, 'x'))

            # Sample colored grid
            colored_start_x = start_x + (self.colorless_width * self.grid_size) + self.line_spacing
            sample_x = colored_start_x + x * self.grid_size + self.grid_size // 2
            r, g, _ = line_data[sample_y][sample_x]
            color_val = (r // 16) & 0xF  # Only use red channel
            colored_values.append(format(color_val, 'x'))

        return (''.join(colorless_values), ''.join(colored_values))

    def verify_pass_image(self, image_path: str, user_pass: UserPass) -> tuple[bool, list[str], Image.Image]:
        """Verify a pass image and return (is_valid, discrepancies, marked_image)"""
        discrepancies = []
        
        try:
            image = Image.open(image_path)
            if image.size != (self.width, self.height):
                discrepancies.append("Invalid image dimensions")
                return False, discrepancies, image

            # Extract and verify both parts
            extracted_colorless, extracted_colored = self.extract_verification_line(image)
            
            # Normalize expected values
            expected_colorless = user_pass.pass_identifier.colorless_part[:72].ljust(72, '0')
            expected_colored = user_pass.pass_identifier.colored_part[:72].ljust(72, '0')

            # Create a transparent overlay for marking errors
            marked_image = image.copy()
            overlay = Image.new('RGBA', image.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)

            # Mark specific regions if they're invalid
            line_y = self.height - 40
            start_x = (self.width - (self.colorless_width * self.grid_size)) // 2

            if extracted_colorless != expected_colorless:
                discrepancies.append("Invalid faction/nation identifier")
                # Mark colorless region with red overlay
                draw.rectangle(
                    [
                        (start_x, line_y),
                        (start_x + self.colorless_width * self.grid_size, line_y + self.colorless_height * self.grid_size)
                    ],
                    fill=(255, 0, 0, 64),  # Semi-transparent red
                    outline=(255, 0, 0, 255)  # Solid red outline
                )

            if extracted_colored != expected_colored:
                discrepancies.append("Invalid user identifier")
                # Mark colored region with red overlay
                colored_start_x = start_x + (self.colorless_width * self.grid_size) + self.line_spacing
                draw.rectangle(
                    [
                        (colored_start_x, line_y),
                        (colored_start_x + self.colored_width * self.grid_size, line_y + self.colored_height * self.grid_size)
                    ],
                    fill=(255, 0, 0, 64),  # Semi-transparent red
                    outline=(255, 0, 0, 255)  # Solid red outline
                )

            if datetime.now() > user_pass.expiry_date:
                discrepancies.append("Pass expired")
                # Add red border around the entire pass
                draw.rectangle(
                    [(0, 0), (self.width-1, self.height-1)],
                    outline=(255, 0, 0, 255),
                    width=3
                )

            # Paste the overlay onto the original image
            marked_image.paste(overlay, (0, 0), overlay)

            if discrepancies:
                print("\nVerification details:")
                if extracted_colorless != expected_colorless:
                    print(f"Expected colorless: {expected_colorless}")
                    print(f"Extracted colorless: {extracted_colorless}")
                if extracted_colored != expected_colored:
                    print(f"Expected colored: {expected_colored}")
                    print(f"Extracted colored: {extracted_colored}")

            return len(discrepancies) == 0, discrepancies, marked_image

        except Exception as e:
            discrepancies.append(f"Error processing image: {str(e)}")
            return False, discrepancies, Image.new('RGB', (self.width, self.height), 'white')

    def _generate_default_icon(self, letter: str) -> Image.Image:
        """Generate a default icon with the given letter and a random color"""
        size = (50, 50)
        img = Image.new('RGB', size, color=(255, 255, 255))
        draw = ImageDraw.Draw(img)
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
        
        # Generate random color
        color = tuple(random.randint(0, 255) for _ in range(3))
        
        # Draw circular vignette
        draw.ellipse([(0, 0), size], fill=color)
        
        # Draw the letter
        text_size = draw.textsize(letter, font=font)
        text_position = ((size[0] - text_size[0]) // 2, (size[1] - text_size[1]) // 2)
        draw.text(text_position, letter, fill=(255, 255, 255), font=font)
        
        return img
