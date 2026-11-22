// Підключення API для публікації коментарів та новин

document.addEventListener('DOMContentLoaded', function() {
    const commentForm = document.getElementById('comment-form');
    if (commentForm) {
        commentForm.addEventListener('submit', async function(e) {
            e.preventDefault();

            const name = document.getElementById('comment-name').value;
            const text = document.getElementById('comment-text').value;

            try {
                const response = await fetch('/api/comments', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name, text })
                });

                if (response.ok) {
                    alert('Ваш коментар опубліковано!');
                    commentForm.reset();
                } else {
                    throw new Error('Помилка при публікації коментарю');
                }
            } catch (error) {
                console.error('Помилка:', error);
                alert('Не вдалося опублікувати коментар. Будь ласка, спробуйте ще раз.');
            }
        });
    }
});