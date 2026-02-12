import os
import logging
from typing import List, Dict
from chess_tools.lib.models import CrucialMoment

logger = logging.getLogger("chess_transfer")

def generate_markdown_report(moments: List[CrucialMoment], metadata: Dict[str, str], output_dir: str = "analysis", summary: str = None):
    """
    Generates a Markdown report from the analyzed moments.
    
    Args:
        moments (List[CrucialMoment]): The list of analyzed moments.
        metadata (Dict[str, str]): Game metadata (White, Black, Date, etc.).
        output_dir (str): Directory to save the report and images.
        summary (str, optional): The LLM generated summary of the game.
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # Create images subdirectory
    images_dir = os.path.join(output_dir, "images")
    if not os.path.exists(images_dir):
        os.makedirs(images_dir)

    # Create filename: Date_White_vs_Black.md
    safe_date = metadata['Date'].replace('.', '-')
    safe_white = "".join(c for c in metadata['White'] if c.isalnum() or c in (' ', '_')).replace(' ', '_')
    safe_black = "".join(c for c in metadata['Black'] if c.isalnum() or c in (' ', '_')).replace(' ', '_')
    filename = f"{safe_date}_{safe_white}_vs_{safe_black}.md"
    output_path = os.path.join(output_dir, filename)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"# Analysis: {metadata['White']} vs {metadata['Black']}\n\n")
        f.write(f"**Date:** {metadata['Date']} | **Event:** {metadata['Event']} | **Site:** {metadata['Site']}\n\n")
        
        if not moments:
            f.write("No crucial moments (blunders/missed wins) detected for the hero in this game.\n")
            logger.info(f"Report generated (empty): {output_path}")
            return

        f.write(f"Found **{len(moments)}** crucial moments where evaluation dropped significantly.\n\n")
        
        for i, moment in enumerate(moments, 1):
            # Save SVG to file
            image_filename = f"{filename.replace('.md', '')}_moment_{i}.svg"
            image_path = os.path.join(images_dir, image_filename)
            
            if moment.svg_content:
                with open(image_path, "w") as img_file:
                    img_file.write(moment.svg_content)
            
            # Relative path for Markdown
            relative_image_path = f"images/{image_filename}"

            f.write(f"## Moment {i}\n\n")
            f.write(f"![Position]({relative_image_path})\n\n")
            f.write(f"**FEN:** `{moment.fen}`\n\n")
            f.write(f"- **You Played:** **{moment.move_played_san}** <span style='color:red'>❌ (Red Arrow)</span>\n")
            f.write(f"- **Engine Best:** **{moment.best_move_san}** <span style='color:green'>✅ (Green Arrow)</span>\n")
            f.write(f"- **Eval Swing:** {moment.eval_swing} cp\n")
            f.write(f"- **Variation:** _{moment.pv_line}_\n\n")
            
            if moment.tactical_alert:
                f.write(f"> **⚠️ {moment.tactical_alert}**\n\n")

            f.write(f"### Coach Explanation\n")
            f.write(f"{moment.explanation}\n\n")
            f.write("---\n")
        
        if summary:
            f.write("\n" + summary + "\n")
            
    logger.info(f"Report generated: {output_path}")
